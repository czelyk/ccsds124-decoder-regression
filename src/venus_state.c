#include "ccsds124.h"
#include <string.h>

enum { PACKET_BYTES = 90, PACKET_BITS = PACKET_BYTES * 8, CRC_BYTES = 4, ROBUSTNESS = 2 };
uint8_t input_bytes[PACKET_BYTES], decoded_bytes[PACKET_BYTES], basic_bytes[PACKET_BYTES];
uint8_t wire_bytes[CCSDS124_MAX_OUTPUT_BYTES + CRC_BYTES];
uint32_t reference_period, inject_at, inject_bit;
uint32_t encoded_bytes, encoded_bits, source_crc, decoded_crc, delivered;
uint32_t flipped_from;
uint32_t basic_crc, basic_delivered, reference_sent;
uint32_t protect_mask, inject_after_check, forced_reference, mask_bytes_checked;
int32_t decode_rc, basic_rc;
uint8_t decode_status;

static ccsds124_compressor_t sender;
static ccsds124_decompressor_t receiver;
static ccsds124_decompressor_t basic_receiver, basic_trial;
static bitvector_t input, decoded;
static bitbuffer_t packet;
static uint32_t frame_index;
static uint32_t mask_seal;

#ifdef VENUS_LOCAL_VERIFY
uint32_t local_verify_enabled, local_attempts, local_retry;
static ccsds124_compressor_t sender_checkpoint;
#ifdef VENUS_VERIFY_SWAP
static ccsds124_decompressor_t local_states[2];
static unsigned local_active;
#else
static ccsds124_decompressor_t local_receiver, local_trial;
#endif
static bitvector_t local_decoded;
static uint8_t local_bytes[PACKET_BYTES];
#endif

void *memcpy(void *dst, const void *src, size_t count)
{
    uint8_t *out = dst;
    const uint8_t *in = src;
    while (count--)
        *out++ = *in++;
    return dst;
}

void *memset(void *dst, int value, size_t count)
{
    uint8_t *out = dst;
    while (count--)
        *out++ = (uint8_t)value;
    return dst;
}

int memcmp(const void *left, const void *right, size_t count)
{
    const uint8_t *a = left, *b = right;
    for (; count; --count, ++a, ++b)
        if (*a != *b)
            return *a - *b;
    return 0;
}

static uint32_t crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8u; ++bit)
            crc = (crc >> 1) ^ ((crc & 1u) ? UINT32_C(0xedb88320) : 0u);
    }
    return ~crc;
}

static uint32_t mask_crc(void)
{
    return crc32((const uint8_t *)sender.mask.data, sizeof(sender.mask.data));
}

static void inject_mask_fault(void)
{
    flipped_from = (uint32_t)bitvector_get_bit(&sender.mask, inject_bit);
    bitvector_set_bit(&sender.mask, inject_bit, !flipped_from);
}

static int evaluate(uint8_t *output, uint32_t *computed, uint32_t *accept, uint32_t tag)
{
    if (bitvector_to_bytes(&decoded, output, PACKET_BYTES) != CCSDS124_OK)
        return 1;
    *computed = crc32(output, PACKET_BYTES);
    *accept = *computed == tag;
    return 0;
}

static int encode_wire(const ccsds124_params_t *params)
{
    bitbuffer_init(&packet);
    if (ccsds124_compress_packet(&sender, &input, &packet, params) != CCSDS124_OK)
        return 2;
    encoded_bits = (uint32_t)bitbuffer_size(&packet);
    encoded_bytes = (uint32_t)bitbuffer_to_bytes(&packet, wire_bytes, CCSDS124_MAX_OUTPUT_BYTES);
    return encoded_bytes != 0 && encoded_bytes == (encoded_bits + 7u) / 8u ? 0 : 3;
}

#ifdef VENUS_LOCAL_VERIFY
static int verify_wire(void)
{
    bitreader_t reader;
    ++local_attempts;
    bitreader_init(&reader, wire_bytes, encoded_bits);
#ifdef VENUS_VERIFY_SWAP
    ccsds124_decompressor_t *trial = &local_states[local_active ^ 1u];
#ifndef VENUS_VERIFY_FIXED_COPY
    ccsds124_decompressor_t *committed = &local_states[local_active];
#endif
#else
    ccsds124_decompressor_t *committed = &local_receiver;
    ccsds124_decompressor_t *trial = &local_trial;
#endif
#ifdef VENUS_VERIFY_FIXED_COPY
    /* Keep both addresses visible to the compiler in each copy. */
    if (local_active)
        memcpy(&local_states[0], &local_states[1], sizeof(*trial));
    else
        memcpy(&local_states[1], &local_states[0], sizeof(*trial));
#else
    memcpy(trial, committed, sizeof(*trial));
#endif
    if (ccsds124_decompress_packet(trial, &reader, &local_decoded) != CCSDS124_OK ||
        bitreader_remaining(&reader) != 0 ||
        bitvector_to_bytes(&local_decoded, local_bytes, PACKET_BYTES) != CCSDS124_OK ||
        memcmp(local_bytes, input_bytes, PACKET_BYTES) != 0)
        return 0;
#ifdef VENUS_VERIFY_SWAP
    /* The trial is now committed. A failed trial never advances this index. */
    local_active ^= 1u;
#else
    memcpy(committed, trial, sizeof(*committed));
#endif
    return 1;
}
#endif

int initialize(void)
{
    if (reference_period == 0 || (inject_at != UINT32_MAX && inject_bit >= PACKET_BITS))
        return 1;
    frame_index = 0;
    flipped_from = UINT32_MAX;
    if (ccsds124_compressor_init(&sender, PACKET_BITS, NULL, ROBUSTNESS, 0, 0, 0) != CCSDS124_OK ||
        ccsds124_decompressor_init(&receiver, PACKET_BITS, NULL, ROBUSTNESS) != CCSDS124_OK ||
        ccsds124_decompressor_init(&basic_receiver, PACKET_BITS, NULL, ROBUSTNESS) != CCSDS124_OK)
        return 2;
    if (protect_mask)
        mask_seal = mask_crc();
#ifdef VENUS_LOCAL_VERIFY
#ifdef VENUS_VERIFY_SWAP
    local_active = 0;
    ccsds124_decompressor_t *committed = &local_states[local_active];
#else
    ccsds124_decompressor_t *committed = &local_receiver;
#endif
    if (local_verify_enabled &&
        ccsds124_decompressor_init(committed, PACKET_BITS, NULL, ROBUSTNESS) != CCSDS124_OK)
        return 2;
#endif
    return bitvector_init(&input, PACKET_BITS);
}

int prepare_packet(void)
{
    if (bitvector_from_bytes(&input, input_bytes, PACKET_BYTES) != CCSDS124_OK)
        return 1;
    source_crc = crc32(input_bytes, PACKET_BYTES);
    if (frame_index == inject_at && !inject_after_check)
        inject_mask_fault();
    forced_reference = protect_mask && mask_crc() != mask_seal;
    if (frame_index == inject_at && inject_after_check)
        inject_mask_fault();

    const uint8_t reference = frame_index <= ROBUSTNESS || frame_index % reference_period == 0 ||
                              forced_reference;
    ccsds124_params_t params = {ROBUSTNESS, frame_index % 20u == 0, reference, reference};

#ifdef VENUS_LOCAL_VERIFY
    local_attempts = 0;
    local_retry = 0;
    if (local_verify_enabled)
        memcpy(&sender_checkpoint, &sender, sizeof(sender_checkpoint));
#endif
    const int encode_rc = encode_wire(&params);
#ifdef VENUS_LOCAL_VERIFY
    if (local_verify_enabled && (encode_rc != 0 || !verify_wire())) {
        local_retry = 1;
        /* The checkpoint already contains any injected persistent mask error.
         * It restores the packet index and history, without healing the fault. */
        memcpy(&sender, &sender_checkpoint, sizeof(sender));
        params.send_mask_flag = 1;
        params.uncompressed_flag = 1;
        if (encode_wire(&params) != 0 || !verify_wire()) {
            memcpy(&sender, &sender_checkpoint, sizeof(sender));
            encoded_bits = 0;
            encoded_bytes = 0;
            return 6;
        }
    } else
#endif
    if (encode_rc != 0)
        return encode_rc;

    reference_sent = params.send_mask_flag;
    if (protect_mask)
        mask_seal = mask_crc();
    mask_bytes_checked = protect_mask ? 2u * (uint32_t)sizeof(sender.mask.data) : 0u;
    for (unsigned i = 0; i < CRC_BYTES; ++i)
        wire_bytes[encoded_bytes + i] = (uint8_t)(source_crc >> (8u * i));
    return 0;
}

int receive_wire(void)
{
    uint32_t received_crc = 0;
    for (unsigned i = 0; i < CRC_BYTES; ++i)
        received_crc |= (uint32_t)wire_bytes[encoded_bytes + i] << (8u * i);

    ccsds124_decompress_result_t details = {0};
    decode_rc = ccsds124_decompress_packet_checked(&receiver, wire_bytes, encoded_bits, &decoded, &details);
    decode_status = details.status;
    delivered = 0;
    decoded_crc = 0;
    if (decode_rc == CCSDS124_OK && decode_status == 0 &&
        evaluate(decoded_bytes, &decoded_crc, &delivered, received_crc))
        return 4;

    bitreader_t reader;
    bitreader_init(&reader, wire_bytes, encoded_bits);
    memcpy(&basic_trial, &basic_receiver, sizeof(basic_trial));
    basic_rc = ccsds124_decompress_packet(&basic_trial, &reader, &decoded);
    if (basic_rc == CCSDS124_OK && bitreader_remaining(&reader) != 0)
        basic_rc = CCSDS124_ERROR_OVERFLOW;
    basic_crc = 0;
    basic_delivered = 0;
    if (basic_rc == CCSDS124_OK) {
        /* Keep parse state on a well-formed packet. Source CRC gates delivery. */
        memcpy(&basic_receiver, &basic_trial, sizeof(basic_receiver));
        if (evaluate(basic_bytes, &basic_crc, &basic_delivered, received_crc))
            return 5;
    }
    ++frame_index;
    return 0;
}

int exchange(void)
{
    const int rc = prepare_packet();
    return rc == 0 ? receive_wire() : rc;
}

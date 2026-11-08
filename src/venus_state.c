#include "ccsds124.h"
#include <string.h>

enum { PACKET_BYTES = 90, PACKET_BITS = PACKET_BYTES * 8, CRC_BYTES = 4, ROBUSTNESS = 2 };
uint8_t input_bytes[PACKET_BYTES], decoded_bytes[PACKET_BYTES], basic_bytes[PACKET_BYTES];
uint8_t wire_bytes[CCSDS124_MAX_OUTPUT_BYTES + CRC_BYTES];
uint32_t reference_period, inject_at, inject_bit;
uint32_t encoded_bytes, encoded_bits, source_crc, decoded_crc, delivered;
uint32_t flipped_from;
uint32_t basic_crc, basic_delivered, reference_sent;
int32_t decode_rc, basic_rc;
uint8_t decode_status;

static ccsds124_compressor_t sender;
static ccsds124_decompressor_t receiver;
static ccsds124_decompressor_t basic_receiver, basic_trial;
static bitvector_t input, decoded;
static bitbuffer_t packet;
static uint32_t frame_index;

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

static uint32_t crc32(const uint8_t *data)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < PACKET_BYTES; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8u; ++bit)
            crc = (crc >> 1) ^ ((crc & 1u) ? UINT32_C(0xedb88320) : 0u);
    }
    return ~crc;
}

static int evaluate(uint8_t *output, uint32_t *computed, uint32_t *accept, uint32_t tag)
{
    if (bitvector_to_bytes(&decoded, output, PACKET_BYTES) != CCSDS124_OK)
        return 1;
    *computed = crc32(output);
    *accept = *computed == tag;
    return 0;
}

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
    return bitvector_init(&input, PACKET_BITS);
}

int exchange(void)
{
    const uint8_t reference = frame_index <= ROBUSTNESS || frame_index % reference_period == 0;
    reference_sent = reference;
    const ccsds124_params_t params = {ROBUSTNESS, frame_index % 20u == 0, reference, reference};
    if (bitvector_from_bytes(&input, input_bytes, PACKET_BYTES) != CCSDS124_OK)
        return 1;
    source_crc = crc32(input_bytes);
    if (frame_index == inject_at) {
        flipped_from = (uint32_t)bitvector_get_bit(&sender.mask, inject_bit);
        bitvector_set_bit(&sender.mask, inject_bit, !flipped_from);
    }

    bitbuffer_init(&packet);
    if (ccsds124_compress_packet(&sender, &input, &packet, &params) != CCSDS124_OK)
        return 2;
    encoded_bits = (uint32_t)bitbuffer_size(&packet);
    encoded_bytes = (uint32_t)bitbuffer_to_bytes(&packet, wire_bytes, CCSDS124_MAX_OUTPUT_BYTES);
    if (encoded_bytes == 0 || encoded_bytes != (encoded_bits + 7u) / 8u)
        return 3;
    for (unsigned i = 0; i < CRC_BYTES; ++i)
        wire_bytes[encoded_bytes + i] = (uint8_t)(source_crc >> (8u * i));

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

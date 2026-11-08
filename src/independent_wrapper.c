#include "ccsds124.h"
#include <stdint.h>
#include <stddef.h>
uint8_t input_bytes[64], output_bytes[13], observed_flags[4];
uint32_t input_bits;
ccsds124_decompressor_t instance;
bitvector_t output_vector;
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d; const unsigned char *b=s; while(n--)*a++=*b++; return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d; while(n--)*a++=(unsigned char)x; return d;}
int memcmp(const void *d,const void *s,size_t n){const unsigned char *a=d,*b=s; while(n--){if(*a!=*b)return *a-*b; a++;b++;}return 0;}
int initialize(void){return ccsds124_decompressor_init(&instance,104,0,0);}
int erase_one(void){return ccsds124_decompressor_notify_packet_loss(&instance,1);}
int receive(void){ccsds124_decompress_result_t details; int rc=ccsds124_decompress_packet_checked(&instance,input_bytes,input_bits,&output_vector,&details); bitvector_to_bytes(&output_vector,output_bytes,13); observed_flags[0]=details.status;observed_flags[1]=details.Vt;observed_flags[2]=details.ft;observed_flags[3]=details.rt;return rc;}


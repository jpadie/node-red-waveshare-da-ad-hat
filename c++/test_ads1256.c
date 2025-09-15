#include "ADS1256_pi.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Usage: %s <channel> [gain] [buffered] [differential] [neg_channel]\n", argv[0]);
        printf("  channel: 0-7\n");
        printf("  gain: 1,2,4,8,16,32,64 (default: 1)\n");
        printf("  buffered: 0 or 1 (default: 0)\n");
        printf("  differential: 0 or 1 (default: 0)\n");
        printf("  neg_channel: 0-7 (default: 1)\n");
        return 1;
    }
    
    int channel = atoi(argv[1]);
    int gain = (argc > 2) ? atoi(argv[2]) : 1;
    bool buffered = (argc > 3) ? (atoi(argv[3]) != 0) : false;
    bool differential = (argc > 4) ? (atoi(argv[4]) != 0) : false;
    int neg_channel = (argc > 5) ? atoi(argv[5]) : 1;
    
    // Initialize ADC
    if (ads1256_init() != 0) {
        printf("Failed to initialize ADC\n");
        return 1;
    }
    
    // Run system offset calibration first
    ads1256_sysocal();
    
    // Read channel
    int32_t raw = ads1256_read_channel(channel, gain, buffered, differential, neg_channel);
    
    // Calculate voltage
    float voltage_mv = (raw / (float)((1 << 23) - 1)) * (2.5f * 1000.0f) / gain;
    
    printf("RAW: %d\n", raw);
    printf("VOLTAGE_MV: %.3f\n", voltage_mv);
    printf("CHANNEL: %d\n", channel);
    printf("GAIN: %d\n", gain);
    printf("DIFF: %d\n", differential ? 1 : 0);
    if (differential) {
        printf("NEG_CHANNEL: %d\n", neg_channel);
    }
    printf("VREF: 2.5\n");
    
    ads1256_cleanup();
    return 0;
}

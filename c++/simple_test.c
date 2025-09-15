#include "ADS1256_pi.h"
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    // Initialize ADC
    if (ads1256_init() != 0) {
        printf("Failed to initialize ADC\n");
        return 1;
    }
    
    // Run system offset calibration first
    ads1256_sysocal();
    
    // Read ADC1 in single-ended mode: channel=1, gain=1, buffered=false, differential=false
    int32_t raw = ads1256_read_channel(1, 1, false, false, 1);
    
    printf("RAW: %d\n", raw);
    
    ads1256_cleanup();
    return 0;
}

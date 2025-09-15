#include "ADS1256_pi.h"
#include <stdio.h>
#include <stdlib.h>

// Global variables
static int spi_fd = -1;
static bool initialized = false;

// GPIO control functions for Waveshare HAT
static int gpio_export(int pin) {
    char buffer[64];
    int fd = open("/sys/class/gpio/export", O_WRONLY);
    if (fd < 0) {
        printf("Failed to open /sys/class/gpio/export: %d\n", fd);
        return -1;
    }
    int len = snprintf(buffer, sizeof(buffer), "%d", pin);
    int result = write(fd, buffer, len);
    close(fd);
    if (result != len) {
        printf("Failed to write to export file for pin %d\n", pin);
        return -1;
    }
    printf("Exported GPIO pin %d\n", pin);
    return 0;
}

static int gpio_unexport(int pin) {
    char buffer[64];
    int fd = open("/sys/class/gpio/unexport", O_WRONLY);
    if (fd < 0) return -1;
    int len = snprintf(buffer, sizeof(buffer), "%d", pin);
    write(fd, buffer, len);
    close(fd);
    return 0;
}

static int gpio_direction(int pin, int dir) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/direction", pin);
    int fd = open(path, O_WRONLY);
    if (fd < 0) return -1;
    write(fd, dir ? "out" : "in", dir ? 3 : 2);
    close(fd);
    return 0;
}

static int gpio_write(int pin, int value) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/value", pin);
    int fd = open(path, O_WRONLY);
    if (fd < 0) return -1;
    write(fd, value ? "1" : "0", 1);
    close(fd);
    return 0;
}

static int gpio_read(int pin) {
    char path[64];
    char value;
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/value", pin);
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    read(fd, &value, 1);
    close(fd);
    return value == '1';
}

// Hardcoded GPIO functions for Waveshare HAT
static void set_cs(bool state) {
    gpio_write(CS_PIN, state ? 1 : 0);
    usleep(1); // 1μs delay
}

static void set_rst(bool state) {
    gpio_write(RST_PIN, state ? 1 : 0);
}

static int read_drdy(void) {
    return gpio_read(DRDY_PIN);
}

// Initialize the ADS1256 on Raspberry Pi
int ads1256_init(void) {
    if (initialized) return 0;
    
    // Export GPIO pins
    printf("Exporting GPIO pins...\n");
    if (gpio_export(CS_PIN) < 0) {
        printf("Failed to export CS_PIN (%d)\n", CS_PIN);
        return -1;
    }
    if (gpio_export(RST_PIN) < 0) {
        printf("Failed to export RST_PIN (%d)\n", RST_PIN);
        return -1;
    }
    if (gpio_export(DRDY_PIN) < 0) {
        printf("Failed to export DRDY_PIN (%d)\n", DRDY_PIN);
        return -1;
    }
    
    // Set GPIO directions
    printf("Setting GPIO directions...\n");
    if (gpio_direction(CS_PIN, 1) < 0) {
        printf("Failed to set CS_PIN direction\n");
        return -1;
    }
    if (gpio_direction(RST_PIN, 1) < 0) {
        printf("Failed to set RST_PIN direction\n");
        return -1;
    }
    if (gpio_direction(DRDY_PIN, 0) < 0) {
        printf("Failed to set DRDY_PIN direction\n");
        return -1;
    }
    
    // Initialize SPI
    spi_fd = open(SPI_DEVICE, O_RDWR);
    if (spi_fd < 0) {
        printf("Failed to open SPI device\n");
        return -1;
    }
    
    // Configure SPI mode
    uint8_t mode = SPI_MODE_1; // CPOL=0, CPHA=1
    if (ioctl(spi_fd, SPI_IOC_WR_MODE, &mode) < 0) {
        printf("Failed to set SPI mode\n");
        close(spi_fd);
        return -1;
    }
    
    // Configure SPI bits per word
    uint8_t bits = 8;
    if (ioctl(spi_fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0) {
        printf("Failed to set SPI bits per word\n");
        close(spi_fd);
        return -1;
    }
    
    // Configure SPI max speed
    uint32_t speed = 1000000; // 1MHz
    if (ioctl(spi_fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) < 0) {
        printf("Failed to set SPI speed\n");
        close(spi_fd);
        return -1;
    }
    
    // Reset ADC
    set_rst(false);
    usleep(1000); // 1ms
    set_rst(true);
    usleep(100000); // 100ms startup delay
    
    // Send reset command
    ads1256_write_command(CMD_RESET);
    usleep(100000); // 100ms after reset
    
    initialized = true;
    printf("ADS1256 initialized successfully\n");
    return 0;
}

void ads1256_cleanup(void) {
    if (spi_fd != -1) {
        close(spi_fd);
        spi_fd = -1;
    }
    
    // Unexport GPIO pins
    gpio_unexport(CS_PIN);
    gpio_unexport(RST_PIN);
    gpio_unexport(DRDY_PIN);
    
    initialized = false;
}

// Wait for DRDY pin to go low
bool ads1256_wait_drdy(int timeout_ms) {
    int timeout = timeout_ms;
    while (read_drdy() == 1 && timeout > 0) {
        usleep(1000); // 1ms
        timeout--;
    }
    return timeout > 0;
}


// SPI transfer function
uint8_t spi_transfer(uint8_t data) {
    uint8_t result = data;
    struct spi_ioc_transfer tr = {
        .tx_buf = (unsigned long)&data,
        .rx_buf = (unsigned long)&result,
        .len = 1,
        .speed_hz = 1000000,
        .bits_per_word = 8,
    };
    
    if (ioctl(spi_fd, SPI_IOC_MESSAGE(1), &tr) < 0) {
        printf("SPI transfer failed\n");
        return 0;
    }
    
    return result;
}

// Write a command to the ADC
void ads1256_write_command(uint8_t cmd) {
    set_cs(false);
    spi_transfer(cmd);
    set_cs(true);
    usleep(10); // 10μs delay
}

// Write a register
void ads1256_write_register(uint8_t reg, uint8_t value) {
    set_cs(false);
    spi_transfer(CMD_WREG | (reg & 0x0F));
    spi_transfer(0x00); // number of registers - 1
    spi_transfer(value);
    set_cs(true);
    usleep(10);
}

// Read a register
uint8_t ads1256_read_register(uint8_t reg) {
    uint8_t result = 0;
    set_cs(false);
    spi_transfer(CMD_RREG | (reg & 0x0F));
    spi_transfer(0x00); // number of registers - 1
    usleep(10);
    result = spi_transfer(0x00);
    set_cs(true);
    return result;
}

// Configure ADC for specific channel and settings
void ads1256_configure(int channel, int gain, bool buffered, bool differential, int neg_channel) {
    // Stop continuous read mode
    ads1256_write_command(CMD_SDATAC);
    usleep(1000);
    
    // Configure STATUS register
    uint8_t status_val = STATUS_ACAL_ENABLED | (buffered ? STATUS_BUFEN_ENABLED : 0);
    ads1256_write_register(REG_STATUS, status_val);
    
    // Configure MUX register
    uint8_t mux_val;
    if (differential) {
        mux_val = (channel << 4) | (neg_channel & 0x0F);
    } else {
        mux_val = (channel << 4) | MUX_AINCOM;
    }
    ads1256_write_register(REG_MUX, mux_val);
    
    // Configure ADCON register (gain)
    uint8_t adcon_val = 0x00;
    switch(gain) {
        case 1: adcon_val = ADCON_PGA_1; break;
        case 2: adcon_val = ADCON_PGA_2; break;
        case 4: adcon_val = ADCON_PGA_4; break;
        case 8: adcon_val = ADCON_PGA_8; break;
        case 16: adcon_val = ADCON_PGA_16; break;
        case 32: adcon_val = ADCON_PGA_32; break;
        case 64: adcon_val = ADCON_PGA_64; break;
        default: adcon_val = ADCON_PGA_1; break;
    }
    ads1256_write_register(REG_ADCON, adcon_val);
    
    // Configure DRATE register
    ads1256_write_register(REG_DRATE, DRATE_10_SPS);
    
    printf("ADC configured: CH=%d, GAIN=%d, BUF=%s, DIFF=%s\n", 
           channel, gain, buffered ? "ON" : "OFF", differential ? "ON" : "OFF");
}

// System offset calibration
void ads1256_sysocal(void) {
    printf("Running system offset calibration...\n");
    if (!ads1256_wait_drdy(1000)) {
        printf("DRDY timeout before SYSOCAL\n");
        return;
    }
    ads1256_write_command(CMD_SYSOCAL);
    if (!ads1256_wait_drdy(10000)) {
        printf("SYSOCAL timeout\n");
    } else {
        printf("SYSOCAL completed\n");
    }
}

// System gain calibration  
void ads1256_sysgcal(void) {
    printf("Running system gain calibration...\n");
    if (!ads1256_wait_drdy(1000)) {
        printf("DRDY timeout before SYSGCAL\n");
        return;
    }
    ads1256_write_command(CMD_SYSGCAL);
    if (!ads1256_wait_drdy(10000)) {
        printf("SYSGCAL timeout\n");
    } else {
        printf("SYSGCAL completed\n");
    }
}

// Self offset calibration
void ads1256_selfocal(void) {
    printf("Running self offset calibration...\n");
    if (!ads1256_wait_drdy(1000)) {
        printf("DRDY timeout before SELFOCAL\n");
        return;
    }
    ads1256_write_command(CMD_SELFOCAL);
    if (!ads1256_wait_drdy(10000)) {
        printf("SELFOCAL timeout\n");
    } else {
        printf("SELFOCAL completed\n");
    }
}

// Self gain calibration
void ads1256_selfgcal(void) {
    printf("Running self gain calibration...\n");
    if (!ads1256_wait_drdy(1000)) {
        printf("DRDY timeout before SELFGCAL\n");
        return;
    }
    ads1256_write_command(CMD_SELFGCAL);
    if (!ads1256_wait_drdy(10000)) {
        printf("SELFGCAL timeout\n");
    } else {
        printf("SELFGCAL completed\n");
    }
}

// Self calibration (both offset and gain)
void ads1256_selfcal(void) {
    printf("Running self calibration...\n");
    if (!ads1256_wait_drdy(1000)) {
        printf("DRDY timeout before SELFCAL\n");
        return;
    }
    ads1256_write_command(CMD_SELFCAL);
    if (!ads1256_wait_drdy(10000)) {
        printf("SELFCAL timeout\n");
    } else {
        printf("SELFCAL completed\n");
    }
}

// Read a single channel
int32_t ads1256_read_channel(int channel, int gain, bool buffered, bool differential, int neg_channel) {
    if (!initialized) {
        printf("ADC not initialized\n");
        return 0;
    }
    
    // Configure ADC
    ads1256_configure(channel, gain, buffered, differential, neg_channel);
    
    // Wait for DRDY
    if (!ads1256_wait_drdy(1000)) {
        printf("DRDY timeout\n");
        return 0;
    }
    
    // Start conversion
    set_cs(false);
    spi_transfer(CMD_SYNC);
    usleep(1);
    spi_transfer(CMD_WAKEUP);
    set_cs(true);
    
    // Wait for conversion
    if (!ads1256_wait_drdy(1000)) {
        printf("Conversion timeout\n");
        return 0;
    }
    
    // Read data
    set_cs(false);
    spi_transfer(CMD_RDATA);
    usleep(10);
    uint8_t data[3];
    data[0] = spi_transfer(0x00);
    data[1] = spi_transfer(0x00);
    data[2] = spi_transfer(0x00);
    set_cs(true);
    
    // Convert to 24-bit signed integer
    int32_t result = ((int32_t)data[0] << 16) | ((int32_t)data[1] << 8) | data[2];
    if (result & 0x800000) {
        result -= 0x1000000; // Sign extend
    }
    
    return result;
}
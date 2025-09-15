#ifndef ADS1256_PI_H_
#define ADS1256_PI_H_

#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <string.h>

// GPIO Pin definitions for Raspberry Pi (BCM numbering)
#define CS_PIN 8          // Chip Select (BCM 8)
#define RST_PIN 25        // Reset (BCM 25) 
#define DRDY_PIN 24       // Data Ready (BCM 24)
#define SPI_DEVICE "/dev/spidev0.0"

// ADS1256 Commands
#define CMD_RESET 0xFE
#define CMD_SDATAC 0x0F
#define CMD_RDATA 0x01
#define CMD_SYNC 0xFC
#define CMD_WAKEUP 0x00
#define CMD_SELFCAL 0xF0
#define CMD_SELFOCAL 0xF1
#define CMD_SELFGCAL 0xF2
#define CMD_SYSOCAL 0xF3
#define CMD_SYSGCAL 0xF4
#define CMD_WREG 0x50
#define CMD_RREG 0x10

// ADS1256 Registers
#define REG_STATUS 0x00
#define REG_MUX 0x01
#define REG_ADCON 0x02
#define REG_DRATE 0x03

// STATUS register values
#define STATUS_ACAL_ENABLED 0x04
#define STATUS_BUFEN_ENABLED 0x02

// MUX register values for single-ended
#define MUX_AINCOM 0x08

// ADCON register values
#define ADCON_PGA_1 0x00
#define ADCON_PGA_2 0x01
#define ADCON_PGA_4 0x02
#define ADCON_PGA_8 0x03
#define ADCON_PGA_16 0x04
#define ADCON_PGA_32 0x05
#define ADCON_PGA_64 0x06

// DRATE register values
#define DRATE_10_SPS 0x20

// Function prototypes
int ads1256_init(void);
void ads1256_cleanup(void);
int32_t ads1256_read_channel(int channel, int gain, bool buffered, bool differential, int neg_channel);
void ads1256_configure(int channel, int gain, bool buffered, bool differential, int neg_channel);
void ads1256_sysocal(void);
void ads1256_sysgcal(void);
void ads1256_selfocal(void);
void ads1256_selfgcal(void);
void ads1256_selfcal(void);
bool ads1256_wait_drdy(int timeout_ms);
void ads1256_write_register(uint8_t reg, uint8_t value);
uint8_t ads1256_read_register(uint8_t reg);
void ads1256_write_command(uint8_t cmd);

#endif /* ADS1256_PI_H_ */

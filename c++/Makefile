CC = gcc
CFLAGS = -Wall -Wextra -O2
LIBS = 

TARGET1 = test_ads1256
TARGET2 = simple_test
SOURCES1 = ADS1256_pi.c test_ads1256.c
SOURCES2 = ADS1256_pi.c simple_test.c

$(TARGET1): $(SOURCES1)
	$(CC) $(CFLAGS) -o $(TARGET1) $(SOURCES1) $(LIBS)

$(TARGET2): $(SOURCES2)
	$(CC) $(CFLAGS) -o $(TARGET2) $(SOURCES2) $(LIBS)

all: $(TARGET1) $(TARGET2)

clean:
	rm -f $(TARGET1) $(TARGET2)

.PHONY: clean all

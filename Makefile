CC      = gcc
CFLAGS  = -O2 -fPIC -Wall -Wextra -march=native
TARGET  = libcore.so
SRC     = steamos_diy_core.c
INSTALL_DIR = /usr/local/lib/steamos_diy

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -shared -o $@ $^

install: $(TARGET)
	install -Dm644 $(TARGET) $(INSTALL_DIR)/$(TARGET)

clean:
	rm -f $(TARGET)

.PHONY: all install clean

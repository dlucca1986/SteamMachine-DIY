CC      = gcc
CFLAGS  = -O2 -fPIC -Wall -Wextra
TARGET  = libcore.so
SRC     = steamos_diy_core.c
DESTDIR = /usr/local/lib/steamos_diy

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -shared -o $@ $^

install: $(TARGET)
	install -Dm644 $(TARGET) $(DESTDIR)/$(TARGET)

clean:
	rm -f $(TARGET)

.PHONY: all install clean

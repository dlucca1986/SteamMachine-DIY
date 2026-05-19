#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>

static char current_tag[64] = "";

// 1. NATIVE LOGGING
__attribute__((visibility("default")))
void c_jlog(const char *tag, const char *msg, int priority) {
    if (tag && strcmp(current_tag, tag) != 0) {
        closelog();
        strncpy(current_tag, tag, sizeof(current_tag) - 1);
        openlog(current_tag, LOG_PID, LOG_USER);
    }
    syslog(priority, "%s", msg);
}

// 2. TTY NOTIFICATION (low-PSI write via O_NOCTTY)
__attribute__((visibility("default")))
void c_notify(const char *status, int clear) {
    int fd = open("/dev/tty1", O_WRONLY | O_NOCTTY);
    if (fd < 0) return;
    if (clear) {
        const char *cls = "\033[H\033[2J\033[3J";
        write(fd, cls, strlen(cls));
    } else {
        char buf[256];
        int len = snprintf(buf, sizeof(buf),
                           "\033[?25l\033[H\033[2J\033[3J\n \033[1m◢◤ SteamOs_Diy\033[0m | %s\n",
                           status);
        write(fd, buf, len);
    }
    close(fd);
}

// 3. ATOMIC WRITE (fdatasync + rename for hardware durability)
__attribute__((visibility("default")))
void c_write_atomic(const char *path, const char *val) {
    if (!path || !val) return;
    char tmp_path[512];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", path);
    int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    size_t len = strlen(val);
    ssize_t written = write(fd, val, len);
    if (written < 0 || (size_t)written != len) {
        close(fd);
        unlink(tmp_path);
        return;
    }
    fdatasync(fd);
    close(fd);
    if (rename(tmp_path, path) != 0) {
        syslog(LOG_ERR, "c_write_atomic: rename %s -> %s: %m", tmp_path, path);
        unlink(tmp_path);
    }
}

// 4. SYSTEMD READINESS NOTIFICATION (handles abstract sockets via '@' prefix)
__attribute__((visibility("default")))
void c_sd_notify_ready() {
    const char *sock_path = getenv("NOTIFY_SOCKET");
    if (!sock_path) return;
    int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (fd < 0) return;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    // NOTIFY_SOCKET may use '@' prefix for abstract sockets (systemd standard)
    if (sock_path[0] == '@') {
        addr.sun_path[0] = '\0';
        strncpy(addr.sun_path + 1, sock_path + 1, sizeof(addr.sun_path) - 2);
    } else {
        strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);
    }
    const char *msg = "READY=1";
    sendto(fd, msg, 7, 0, (const struct sockaddr *)&addr, sizeof(struct sockaddr_un));
    close(fd);
}

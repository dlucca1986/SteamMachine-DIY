#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>

static char current_tag[64] = "";
static pthread_mutex_t tag_lock = PTHREAD_MUTEX_INITIALIZER;

// 1. NATIVE LOGGING
__attribute__((visibility("default")))
void c_jlog(const char *tag, const char *msg, int priority) {
    // ctypes releases the GIL during this call, so two Python threads
    // (e.g. main + post_start_cmds) can race the tag switch; the lock
    // keeps the closelog/openlog/syslog triple coherent per message.
    pthread_mutex_lock(&tag_lock);
    if (tag && strcmp(current_tag, tag) != 0) {
        closelog();
        strncpy(current_tag, tag, sizeof(current_tag) - 1);
        openlog(current_tag, LOG_PID, LOG_USER);
    }
    syslog(priority, "%s", msg);
    pthread_mutex_unlock(&tag_lock);
}

// 2. TTY NOTIFICATION (O_NOCTTY: tty1 never becomes our controlling tty)
__attribute__((visibility("default")))
void c_notify(const char *status, int clear) {
    // O_CLOEXEC: a child forked from another thread mid-call must not
    // inherit this tty fd (ctypes releases the GIL during the C call).
    int fd = open("/dev/tty1", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    if (fd < 0) return;
    if (clear) {
        const char *cls = "\033[H\033[2J\033[3J";
        write(fd, cls, strlen(cls));
    } else {
        char buf[256];
        int len = snprintf(buf, sizeof(buf),
                           "\033[?25l\033[H\033[2J\033[3J\n \033[1m◢◤ SteamOs_Diy\033[0m | %s\n",
                           status);
        // snprintf returns the untruncated length, or <0 on error: clamp
        // so write() never reads past buf or gets a negative length.
        if (len < 0) {
            close(fd);
            return;
        }
        if (len >= (int)sizeof(buf)) len = sizeof(buf) - 1;
        write(fd, buf, len);
    }
    close(fd);
}

// 3. ATOMIC WRITE (fdatasync + rename for hardware durability)
// Returns 1 on success, 0 on any failure (logged via syslog).
__attribute__((visibility("default")))
int c_write_atomic(const char *path, const char *val) {
    if (!path || !val) return 0;
    char tmp_path[512];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", path);
    // O_CLOEXEC: keep this fd out of any concurrently forked child.
    // O_NOFOLLOW: refuse a symlink planted at tmp_path instead of
    // truncating whatever it points at. Today's callers all run as the
    // user, never root, but the guard doesn't depend on that.
    // O_NONBLOCK: a FIFO planted at tmp_path makes the open fail (ENXIO)
    // instead of blocking forever; no effect on a regular file.
    // Mode 0644 applies to the new inode whatever the old file's mode was
    // (rename replaces it) — fine for next_session and the user YAMLs.
    int fd = open(
        tmp_path,
        O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK,
        0644
    );
    if (fd < 0) {
        // ELOOP here is O_NOFOLLOW refusing a symlink at tmp_path.
        syslog(LOG_WARNING, "c_write_atomic: open %s: %m", tmp_path);
        return 0;
    }
    // A FIFO with a reader attached still opens: refuse anything that
    // isn't a regular file, so the rename can never turn the target into
    // a FIFO or device. Not unlinked: we didn't create it.
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
        syslog(LOG_WARNING,
               "c_write_atomic: refusing non-regular tmp path %s", tmp_path);
        close(fd);
        return 0;
    }
    size_t len = strlen(val);
    ssize_t written = write(fd, val, len);
    if (written < 0 || (size_t)written != len) {
        if (written < 0)
            syslog(LOG_WARNING, "c_write_atomic: write %s: %m", tmp_path);
        else
            syslog(LOG_WARNING, "c_write_atomic: short write %s", tmp_path);
        close(fd);
        unlink(tmp_path);
        return 0;
    }
    // Best effort: a failed flush is logged, but the data is fully
    // written, so renaming is still better than discarding it.
    if (fdatasync(fd) != 0) {
        syslog(LOG_WARNING, "c_write_atomic: fdatasync %s: %m", tmp_path);
    }
    close(fd);
    if (rename(tmp_path, path) != 0) {
        syslog(LOG_ERR, "c_write_atomic: rename %s -> %s: %m", tmp_path, path);
        unlink(tmp_path);
        return 0;
    }
    // The rename survives a power loss only once the directory is
    // fsync'd. Best effort and unreported: the rename already succeeded.
    char dir_path[512];
    snprintf(dir_path, sizeof(dir_path), "%s", path);
    char *slash = strrchr(dir_path, '/');
    if (slash) {
        // path directly under root ("/foo") -> keep dir_path as "/"
        // rather than truncating to an empty, unopenable string.
        *(slash == dir_path ? slash + 1 : slash) = '\0';
        int dfd = open(dir_path, O_RDONLY | O_CLOEXEC);
        if (dfd >= 0) {
            fsync(dfd);
            close(dfd);
        }
    }
    return 1;
}

// 4. SYSTEMD READINESS NOTIFICATION (handles abstract sockets via '@' prefix)
__attribute__((visibility("default")))
void c_sd_notify_ready(void) {
    const char *sock_path = getenv("NOTIFY_SOCKET");
    if (!sock_path) return;
    // SOCK_CLOEXEC: don't leak the notify socket into a forked child.
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
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
    // Abstract names are length-delimited: the address length must cover
    // exactly the bytes in use, or the NUL padding becomes part of the
    // name. The same formula works for filesystem paths.
    socklen_t addrlen = offsetof(struct sockaddr_un, sun_path) + strlen(sock_path);
    if (addrlen > sizeof(addr)) addrlen = sizeof(addr);
    const char *msg = "READY=1";
    sendto(fd, msg, strlen(msg), 0, (const struct sockaddr *)&addr, addrlen);
    close(fd);
}

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

// 2. TTY NOTIFICATION (low-PSI write via O_NOCTTY)
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
        // snprintf returns the would-be length (or <0 on encoding error):
        // clamp so an oversized status never makes write() read past the
        // buffer, and never pass a negative length to write().
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
// Returns 1 on success, 0 on any failure (already logged via syslog) — lets
// Python callers stop assuming a write landed just because the call
// returned; a symlink refusal, a short write, or a failed rename are now
// visible to them, not just to whoever happens to grep the journal.
__attribute__((visibility("default")))
int c_write_atomic(const char *path, const char *val) {
    if (!path || !val) return 0;
    char tmp_path[512];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", path);
    // O_CLOEXEC: keep this transient fd out of any concurrently forked child.
    // O_NOFOLLOW: refuse to write through a symlink planted at tmp_path by
    // another process running as this same user, instead of truncating
    // whatever it points at — same TOCTOU guard already applied on the
    // Python side (restore.py::_write_member). No current caller of
    // write_atomic() crosses a privilege boundary (all three run as the
    // invoking user, never root), but this is an exported, generically-
    // loaded primitive with no caller-specific privilege check of its
    // own, so it shouldn't rely on today's call graph to stay safe.
    // O_NONBLOCK: a FIFO planted at tmp_path by the same same-user threat
    // model would otherwise block this open() forever waiting for a
    // reader — every caller (session switch, Control Center save) would
    // hang with no timeout. With O_NONBLOCK, a write-only open on a
    // reader-less FIFO fails immediately (ENXIO) instead. No-op on a
    // regular file per POSIX, so this changes nothing for the normal case.
    // Mode 0644 always applies to the new inode, regardless of the target
    // file's previous permissions (tmp+rename replaces the inode outright,
    // it can't "preserve" the old one) — fine for every current caller
    // (next_session marker, user config YAML), none of which need anything
    // stricter, but worth this note for whoever adds the next one.
    int fd = open(
        tmp_path,
        O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK,
        0644
    );
    if (fd < 0) return 0;
    // A reader could still be attached to a pre-existing FIFO at tmp_path,
    // letting the O_NONBLOCK open above succeed anyway — fstat and refuse
    // anything that isn't a plain file before writing/renaming it over the
    // real target, so this can never turn a config file into a FIFO/device
    // node. Left in place rather than unlinked: we didn't create it, and
    // it isn't ours to delete.
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
        close(fd);
        unlink(tmp_path);
        return 0;
    }
    // Best-effort durability note, not a correctness requirement: unlike
    // the rename() below (whose failure aborts the write outright),
    // fdatasync() failing here doesn't change the control flow — the
    // data is already fully written to the page cache and proceeding to
    // rename() is still strictly better than discarding a completed
    // write over an unconfirmed flush. Logged so a failing/degrading
    // storage device leaves a trace instead of silently not honoring
    // the "hardware durability" this function's own header promises.
    if (fdatasync(fd) != 0) {
        syslog(LOG_WARNING, "c_write_atomic: fdatasync %s: %m", tmp_path);
    }
    close(fd);
    if (rename(tmp_path, path) != 0) {
        syslog(LOG_ERR, "c_write_atomic: rename %s -> %s: %m", tmp_path, path);
        unlink(tmp_path);
        return 0;
    }
    // rename() is atomic, but the directory entry update it makes isn't
    // guaranteed durable across a power loss until the directory itself is
    // fsync'd — this runs on a handheld that can lose power mid-operation
    // (same threat model as the subprocess timeout discipline elsewhere in
    // this project). Best-effort: a failure to open/fsync the directory
    // isn't reported, since the rename itself already succeeded.
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
    // exactly the bytes in use, or the kernel treats the NUL padding as
    // part of the name and the datagram goes to a non-existent socket.
    // The same formula is also valid for filesystem paths.
    socklen_t addrlen = offsetof(struct sockaddr_un, sun_path) + strlen(sock_path);
    if (addrlen > sizeof(addr)) addrlen = sizeof(addr);
    const char *msg = "READY=1";
    sendto(fd, msg, strlen(msg), 0, (const struct sockaddr *)&addr, addrlen);
    close(fd);
}

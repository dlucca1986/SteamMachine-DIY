#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <errno.h>
#include <ctype.h>
#include <sys/socket.h>
#include <sys/un.h>

static char current_tag[64] = "";

// Inlined to eliminate call overhead on the hot path
static inline void trim_inplace(char *s) {
    char *p = s;
    int l = strlen(p);
    while(l > 0 && (isspace((unsigned char)p[l - 1]) || p[l - 1] == '"' || p[l - 1] == '\'')) p[--l] = 0;
    while(*p && (isspace((unsigned char)*p) || *p == '"' || *p == '\'')) p++, l--;
    memmove(s, p, l + 1);
}

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
        write(fd, cls, 11);
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
    char tmp_path[512];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", path);
    int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    write(fd, val, strlen(val));
    fdatasync(fd);
    close(fd);
    rename(tmp_path, path);
}

// 4. SSoT CONFIG READER (key=value parser)
__attribute__((visibility("default")))
int c_get_conf_val(const char *path, const char *key, char *dest, int dest_len) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[512];
    int found = 0;
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#' || line[0] == '\n' || !strchr(line, '=')) continue;
        char *k = strtok(line, "=");
        char *v = strtok(NULL, "\n");
        if (k && v) {
            trim_inplace(k);
            if (strcmp(k, key) == 0) {
                trim_inplace(v);
                strncpy(dest, v, dest_len - 1);
                dest[dest_len - 1] = '\0';
                found = 1;
                break;
            }
        }
    }
    fclose(f);
    return found;
}

// 5. SIMPLE FILE READ (first line only)
__attribute__((visibility("default")))
int c_read_file_simple(const char *path, char *dest, int dest_len) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    if (fgets(dest, dest_len, f)) {
        trim_inplace(dest);
        fclose(f);
        return 1;
    }
    fclose(f);
    return 0;
}

// 6. DETACHED SPAWN (fork/exec, returns child PID or 0 on failure)
__attribute__((visibility("default")))
int c_spawn_detached(const char *path, char *const argv[]) {
    pid_t pid = fork();
    if (pid == 0) {
        setsid();
        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            close(devnull);
        }
        execv(path, argv);
        _exit(1);
    }
    return (pid > 0) ? (int)pid : 0;
}

// 7. PROCESS MONITOR (/proc polling every 200ms, avoids waitpid conflict with Python subprocess)
__attribute__((visibility("default")))
int c_monitor_process(int pid, int timeout_sec) {
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d", pid);
    int iterations = timeout_sec * 5;
    for (int i = 0; i < iterations; i++) {
        if (access(path, F_OK) != 0) return 0;
        usleep(200000);
    }
    return 1;
}

// 8. SYSTEMD READINESS NOTIFICATION (handles abstract sockets via '@' prefix)
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

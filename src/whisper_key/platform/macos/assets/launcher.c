// platform/macos/assets/launcher.c
// Login launcher for macOS (issue #19). autostart.py compiles this into
// ~/Applications/Whisper Local.app with the command that starts Whisper Local
// built in, and the LaunchAgent runs it. It starts that command as its child,
// and macOS checks a child's Accessibility and Microphone access against the
// app that started it, so the grants belong to "Whisper Local" instead of Python.
#include <ApplicationServices/ApplicationServices.h>
#include <errno.h>
#include <libproc.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

// Written by autostart.py at build time: COMMAND, the argv to run. The launcher
// takes no command from outside, so nobody can hand it a different program to
// run with its permissions.
#include "command.h"

extern char **environ;

// How long to wait for the Accessibility grant before starting the app anyway,
// so a declined or missed prompt still ends with the app in the menu bar.
static const long AX_WAIT_SECONDS = 60;

// Carries the end of that wait across re-execs. Set means macOS has prompted.
static const char *WAIT_UNTIL = "WHISPER_LOCAL_AX_WAIT_UNTIL";

// launchd signals only this process when it stops the job. Pass the signal to
// the whole process group so Whisper Local can shut down cleanly.
static void forward_signal(int sig) {
    signal(sig, SIG_IGN);
    kill(0, sig);
}

// The tray's Restart item starts the new instance from the old one, so the app
// can outlive the child started here. launchd kills this process group once
// this process exits, so keep running while anyone else is in it.
static int group_has_others(void) {
    pid_t pids[256] = {0};
    proc_listpids(PROC_PGRP_ONLY, (uint32_t)getpgrp(), pids, sizeof pids);
    for (int i = 0; i < 256; i++)
        if (pids[i] > 0 && pids[i] != getpid()) return 1;
    return 0;
}

// The environment minus the variables that load code into a process: DYLD_*
// for dyld and PYTHON* for Python. The child runs with this app's permissions.
static char **child_environment(void) {
    size_t count = 0;
    while (environ[count]) count++;
    char **env = calloc(count + 1, sizeof *env);
    if (env == NULL) return NULL;
    size_t kept = 0;
    for (size_t i = 0; i < count; i++)
        if (strncmp(environ[i], "DYLD_", 5) != 0 && strncmp(environ[i], "PYTHON", 6) != 0)
            env[kept++] = environ[i];
    return env;
}

int main(void) {
    // Hotkeys and auto-paste need Accessibility, and Whisper Local checks for it
    // once, at startup. Ask macOS here and start the app after the grant, or
    // after AX_WAIT_SECONDS. AXIsProcessTrusted() kept returning its first
    // answer after the grant, so each check runs in a fresh exec of this program.
    const char *wait_until = getenv(WAIT_UNTIL);
    int start;
    if (wait_until) {
        start = AXIsProcessTrusted() || time(NULL) >= atol(wait_until);
    } else {
        const void *keys[] = {kAXTrustedCheckOptionPrompt};
        const void *values[] = {kCFBooleanTrue};
        CFDictionaryRef options = CFDictionaryCreate(NULL, keys, values, 1,
            &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        start = AXIsProcessTrustedWithOptions(options);
        CFRelease(options);
        if (!start) {
            char deadline[32];
            snprintf(deadline, sizeof deadline, "%ld", (long)time(NULL) + AX_WAIT_SECONDS);
            setenv(WAIT_UNTIL, deadline, 1);
        }
    }
    if (!start) {
        char self[PATH_MAX];
        uint32_t size = sizeof self;
        sleep(2);
        if (_NSGetExecutablePath(self, &size) == 0)
            execv(self, (char *[]){self, NULL});
        perror("execv");
        return 126;
    }
    unsetenv(WAIT_UNTIL);

    setpgid(0, 0);
    signal(SIGTERM, forward_signal);
    signal(SIGINT, forward_signal);
    signal(SIGHUP, forward_signal);

    // A signal forwarded before the spawn leaves it ignored here, and ignored
    // signals carry over to the child. Start the child with the defaults.
    sigset_t defaults;
    sigemptyset(&defaults);
    sigaddset(&defaults, SIGTERM);
    sigaddset(&defaults, SIGINT);
    sigaddset(&defaults, SIGHUP);
    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    posix_spawnattr_setsigdefault(&attr, &defaults);
    posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETSIGDEF);

    char **env = child_environment();
    pid_t child;
    int err = env ? posix_spawn(&child, COMMAND[0], NULL, &attr, COMMAND, env) : ENOMEM;
    if (err) {
        fprintf(stderr, "cannot start %s: %s\n", COMMAND[0], strerror(err));
        return 127;
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    while (group_has_others()) sleep(1);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}

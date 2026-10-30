#!/usr/bin/env python3
"""Apply automatic FUSE fallback logic to AppImage type2-runtime runtime.c."""

from __future__ import annotations

import sys
from pathlib import Path

FALLBACK_FUNCTIONS = """
static volatile sig_atomic_t fallback_in_signal_handler = 0;
static char fallback_cleanup_dir[PATH_MAX] = {0};
static pid_t fallback_child_pid = -1;

static void fallback_clean_directory(const char* dir_path) {
    DIR* d = opendir(dir_path);
    if (!d) {
        return;
    }
    struct dirent* entry;
    char path[PATH_MAX];
    while ((entry = readdir(d)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        snprintf(path, sizeof(path), "%s/%s", dir_path, entry->d_name);
        struct stat st;
        if (lstat(path, &st) == 0) {
            if (S_ISDIR(st.st_mode)) {
                chmod(path, 0700);
                fallback_clean_directory(path);
                rmdir(path);
            } else {
                chmod(path, 0600);
                unlink(path);
            }
        }
    }
    closedir(d);
    chmod(dir_path, 0700);
    rmdir(dir_path);
}

static void fallback_signal_handler(int sig) {
    if (fallback_in_signal_handler) {
        return;
    }
    fallback_in_signal_handler = 1;

    if (fallback_child_pid > 0) {
        kill(fallback_child_pid, sig);
        int status;
        waitpid(fallback_child_pid, &status, 0);
    }
    if (fallback_cleanup_dir[0] != '\\0' && getenv("NO_CLEANUP") == NULL) {
        fallback_clean_directory(fallback_cleanup_dir);
        fallback_cleanup_dir[0] = '\\0';
    }
    signal(sig, SIG_DFL);
    raise(sig);
}

static int execute_extracted_fallback(
    const char* appimage_path,
    const char* fullpath,
    const char* argv0_path,
    int argc,
    char* argv[],
    const char* temp_base,
    bool verbose
) {
    if (getenv("APPIMAGE_FALLBACK_ACTIVE") != NULL) {
        fprintf(stderr, "AppImage: FUSE mount failed and recursive fallback was prevented.\\n");
        return EXIT_EXECERROR;
    }

    /* 1. Create a private temporary directory with 0700 permissions */
    char temp_dir[PATH_MAX];
    snprintf(temp_dir, sizeof(temp_dir), "%s/pirate_cinema_extracted_%d_XXXXXX", temp_base, (int) getpid());
    if (mkdtemp(temp_dir) == NULL) {
        perror("Failed to create temporary directory for AppImage fallback");
        return EXIT_EXECERROR;
    }
    chmod(temp_dir, 0700);

    /* Register cleanup directory and signals */
    strncpy(fallback_cleanup_dir, temp_dir, sizeof(fallback_cleanup_dir) - 1);
    fallback_cleanup_dir[sizeof(fallback_cleanup_dir) - 1] = '\\0';

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = fallback_signal_handler;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);
    sigaction(SIGQUIT, &sa, NULL);

    if (verbose) {
        fprintf(stderr, "FUSE unavailable or failed. Extracting AppImage to %s...\\n", temp_dir);
    }

    /* 2. Extract contents */
    if (!extract_appimage(appimage_path, temp_dir, NULL, false, verbose)) {
        fprintf(stderr, "Failed to extract AppImage (image may be corrupt or incomplete)\\n");
        if (getenv("NO_CLEANUP") == NULL) {
            fallback_clean_directory(temp_dir);
            fallback_cleanup_dir[0] = '\\0';
        }
        return EXIT_EXECERROR;
    }

    /* 3. Fork and execute AppRun */
    pid_t child = fork();
    if (child == -1) {
        int error = errno;
        fprintf(stderr, "fork() failed during fallback execution: %s\\n", strerror(error));
        if (getenv("NO_CLEANUP") == NULL) {
            fallback_clean_directory(temp_dir);
            fallback_cleanup_dir[0] = '\\0';
        }
        return EXIT_EXECERROR;
    }

    if (child == 0) {
        /* In child: prepare AppRun path */
        char apprun_path[PATH_MAX];
        snprintf(apprun_path, sizeof(apprun_path), "%s/AppRun", temp_dir);

        /* Prepare argv passing all arguments without modification */
        char* new_argv[argc + 1];
        new_argv[0] = apprun_path;
        for (int i = 1; i < argc; ++i) {
            new_argv[i] = argv[i];
        }
        new_argv[argc] = NULL;

        /* Set AppImage environment variables */
        setenv("APPIMAGE", fullpath, 1);
        setenv("ARGV0", argv0_path, 1);
        setenv("APPDIR", temp_dir, 1);
        setenv("APPIMAGE_FALLBACK_ACTIVE", "1", 1);

        char cwd[PATH_MAX];
        if (getcwd(cwd, sizeof(cwd)) != NULL) {
            setenv("OWD", cwd, 1);
        }

        set_portable_home_and_config((char*) fullpath);

        execv(apprun_path, new_argv);

        int error = errno;
        fprintf(stderr, "Failed to run %s: %s\\n", apprun_path, strerror(error));
        exit(EXIT_EXECERROR);
    }

    /* In parent: wait for child */
    fallback_child_pid = child;
    int status = 0;
    int rv = waitpid(child, &status, 0);
    int exit_code = (rv > 0 && WIFEXITED(status)) ? WEXITSTATUS(status) :
                    (rv > 0 && WIFSIGNALED(status) ? 128 + WTERMSIG(status) : EXIT_EXECERROR);

    fallback_child_pid = -1;
    /* Cleanup temporary files */
    if (getenv("NO_CLEANUP") == NULL) {
        fallback_clean_directory(temp_dir);
        fallback_cleanup_dir[0] = '\\0';
    }

    return exit_code;
}
"""

TARGET_CHILD_MOUNT = """        if (0 != fusefs_main(5, child_argv, fuse_mounted)) {
            char* title;
            char* body;
            title = "Cannot mount AppImage, please check your FUSE setup.";
            body = "You might still be able to extract the contents of this AppImage \\n"
                   "if you run it with the --appimage-extract option. \\n"
                   "See https://github.com/AppImage/AppImageKit/wiki/FUSE \\n"
                   "for more information";
            printf("\\n%s\\n", title);
            printf("%s\\n", body);
        };"""

REPLACEMENT_CHILD_MOUNT = """        if (0 != fusefs_main(5, child_argv, fuse_mounted)) {
            if (verbose) {
                fprintf(stderr, "fusefs_main failed, child exiting\\n");
            }
            exit(1);
        }
        exit(0);"""

TARGET_PARENT_WAIT = """        /* Pause until mounted */
        read(keepalive_pipe[0], &c, 1);

        /* Fuse process has now daemonized, reap our child */
        waitpid(pid, NULL, 0);

        dir_fd = open(mount_dir, O_RDONLY);"""

REPLACEMENT_PARENT_WAIT = """        /* Pause until mounted */
        ssize_t read_bytes = read(keepalive_pipe[0], &c, 1);

        /* Fuse process has now daemonized, reap our child */
        waitpid(pid, NULL, 0);

        if (read_bytes <= 0) {
            /* FUSE mount failed! Clean up empty mount_dir and fallback to automatic extraction */
            close(keepalive_pipe[0]);
            rmdir(mount_dir);

            if (arg && strcmp(arg, "appimage-mount") == 0) {
                fprintf(stderr, "Cannot mount AppImage: FUSE is not available.\\n");
                exit(EXIT_EXECERROR);
            }

            int fallback_code = execute_extracted_fallback(
                appimage_path,
                fullpath,
                argv0_path,
                argc,
                argv,
                temp_base,
                verbose
            );
            exit(fallback_code);
        }

        dir_fd = open(mount_dir, O_RDONLY);"""


def patch_runtime_source(runtime_c_path: Path) -> bool:
    """Patch runtime.c in-place to implement automatic FUSE fallback."""
    content = runtime_c_path.read_text(encoding="utf-8")
    # Normalize CRLF to LF
    content = content.replace("\r\n", "\n")

    if "execute_extracted_fallback" in content:
        print(f"[INFO] {runtime_c_path} is already patched.")
        return True

    # 1. Insert fallback functions before main
    main_marker = "int main(int argc, char* argv[]) {"
    if main_marker not in content:
        raise ValueError(f"Could not find '{main_marker}' in {runtime_c_path}")
    content = content.replace(main_marker, FALLBACK_FUNCTIONS + "\n" + main_marker, 1)

    # 2. Patch child fusefs_main failure handling
    normalized_target_child = TARGET_CHILD_MOUNT.replace("\r\n", "\n")
    if normalized_target_child not in content:
        raise ValueError("Could not find TARGET_CHILD_MOUNT in runtime.c")
    content = content.replace(normalized_target_child, REPLACEMENT_CHILD_MOUNT, 1)

    # 3. Patch parent waitpid and fallback trigger
    normalized_target_parent = TARGET_PARENT_WAIT.replace("\r\n", "\n")
    if normalized_target_parent not in content:
        raise ValueError("Could not find TARGET_PARENT_WAIT in runtime.c")
    content = content.replace(normalized_target_parent, REPLACEMENT_PARENT_WAIT, 1)

    runtime_c_path.write_text(content, encoding="utf-8", newline="\n")
    print(f"[SUCCESS] Patched {runtime_c_path} with automatic FUSE fallback.")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path_to_runtime.c>")
        return 1
    p = Path(sys.argv[1]).resolve()
    if not p.is_file():
        print(f"File not found: {p}")
        return 1
    patch_runtime_source(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())

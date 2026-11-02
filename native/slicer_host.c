/* Trusted Windows bootstrap; native engines remain in a write-restricted LPAC. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>
#include <stdio.h>
#include <errno.h>

typedef int (__stdcall *NativeMain)(int, wchar_t **);
#define TOKEN_FUNCTION(name, result, args) \
    typedef result (WINAPI *name##Function) args; \
    name##Function token_##name = (name##Function)GetProcAddress(platform, #name)

int wmain(int argc, wchar_t **argv)
{
    static const wchar_t *libraries[] = {
        L"user32.dll", L"gdi32.dll", L"bcryptprimitives.dll", L"cryptbase.dll",
        L"bcrypt.dll", L"advapi32.dll", L"ole32.dll", L"oleaut32.dll", L"shell32.dll", NULL
    };
    wchar_t directory[32768], library[32768], *slash, *end;
    const wchar_t *engine_name = NULL;
    const char *entry_name = NULL;
    DWORD length, returned, app_container = 0;
    unsigned __int64 handle_value;
    HANDLE startup_token, primary = NULL, thread_token = NULL;
    HMODULE engine, platform = GetModuleHandleW(L"kernelbase.dll");
    NativeMain entry;
    int index, cli = 0;
    TOKEN_FUNCTION(SetThreadToken, BOOL, (PHANDLE, HANDLE));
    TOKEN_FUNCTION(RevertToSelf, BOOL, (void));
    TOKEN_FUNCTION(OpenThreadToken, BOOL, (HANDLE, DWORD, BOOL, PHANDLE));
    TOKEN_FUNCTION(OpenProcessToken, BOOL, (HANDLE, DWORD, PHANDLE));
    TOKEN_FUNCTION(IsTokenRestricted, BOOL, (HANDLE));
    TOKEN_FUNCTION(GetTokenInformation, BOOL, (HANDLE, TOKEN_INFORMATION_CLASS, LPVOID, DWORD, PDWORD));
    if (argc < 4 || !token_SetThreadToken || !token_RevertToSelf ||
            !token_OpenThreadToken || !token_OpenProcessToken ||
            !token_IsTokenRestricted || !token_GetTokenInformation) return 125;
    length = GetModuleFileNameW(NULL, directory, 32768);
    if (!length || length >= 32768) return 125;
    slash = wcsrchr(directory, L'\\');
    if (!slash) return 125;
    slash[1] = 0;
    length = (DWORD)wcslen(directory);
    if (_wcsnicmp(directory, argv[2], length) != 0) return 125;
    if (_wcsicmp(argv[2] + length, L"AnycubicSlicerNext.exe") == 0) {
        engine_name = L"AnycubicSlicer.dll"; entry_name = "anycubicslicer_main";
    } else if (_wcsicmp(argv[2] + length, L"bambu-studio.exe") == 0 ||
            _wcsicmp(argv[2] + length, L"BambuStudio.exe") == 0) {
        engine_name = L"BambuStudio.dll"; entry_name = "bambustu_main";
    } else if (_wcsicmp(argv[2] + length, L"prusa-slicer.exe") == 0 ||
            _wcsicmp(argv[2] + length, L"PrusaSlicer.exe") == 0) {
        engine_name = L"PrusaSlicer.dll"; entry_name = "slic3r_main";
    } else if (_wcsicmp(argv[2] + length, L"orca-slicer.exe") == 0 ||
            _wcsicmp(argv[2] + length, L"OrcaSlicer.exe") == 0) {
        engine_name = L"OrcaSlicer.dll"; entry_name = "orcaslicer_main";
    } else return 125;
    for (index = 3; index < argc; ++index) {
        if (wcscmp(argv[index], L"--slice") == 0 ||
                wcscmp(argv[index], L"--export-gcode") == 0 ||
                wcscmp(argv[index], L"--export-3mf") == 0 ||
                wcscmp(argv[index], L"--export-stl") == 0 ||
                wcscmp(argv[index], L"--save") == 0) cli = 1;
    }
    if (!cli) return 125;
    errno = 0;
    handle_value = _wcstoui64(argv[1], &end, 10);
    if (errno || end == argv[1] || *end || !handle_value ||
            (unsigned __int64)(ULONG_PTR)handle_value != handle_value) return 125;
    startup_token = (HANDLE)(ULONG_PTR)handle_value;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (!SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)) return 125;
    if (!token_SetThreadToken(NULL, startup_token)) {
        CloseHandle(startup_token);
        return 125;
    }
    CloseHandle(startup_token);
    /* No slicer code or project content is read during this trusted phase. */
    for (index = 0; libraries[index]; ++index) {
        if (!LoadLibraryExW(libraries[index], NULL, LOAD_LIBRARY_SEARCH_SYSTEM32)) {
            DWORD failure = GetLastError();
            token_RevertToSelf();
            fprintf(stderr, "Windows runtime initialization failed (%lu).\n", failure);
            return 125;
        }
    }
    if (!token_RevertToSelf()) return 125;
    if (token_OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &thread_token)) {
        CloseHandle(thread_token);
        return 125;
    }
    if (GetLastError() != ERROR_NO_TOKEN) return 125;
    if (!token_OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &primary)) return 125;
    if (!token_IsTokenRestricted(primary) ||
            !token_GetTokenInformation(primary, TokenIsAppContainer,
                &app_container, sizeof(app_container), &returned) || !app_container) {
        CloseHandle(primary);
        return 125;
    }
    CloseHandle(primary);
    if (swprintf_s(library, 32768, L"%s%s", directory, engine_name) < 0) return 125;
    engine = LoadLibraryExW(library, NULL,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!engine) {
        fprintf(stderr, "Native slicer engine could not be loaded (%lu).\n", GetLastError());
        return 125;
    }
    entry = (NativeMain)GetProcAddress(engine, entry_name);
    if (!entry) return 125;
    return entry(argc - 2, argv + 2);
}

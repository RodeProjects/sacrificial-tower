/* Neutral Windows acceptance payload. Never linked into the application. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <aclapi.h>
#include <sddl.h>
#include <stdio.h>
#include <wchar.h>

__declspec(dllexport) int __stdcall anycubicslicer_main(int argc, wchar_t **argv)
{
    HANDLE file, token;
    wchar_t original[32768], alias[32768], destination[32768], child[32768];
    DWORD written;
    PSECURITY_DESCRIPTOR descriptor = NULL;
    PACL acl = NULL;
    BOOL present, defaulted;
    STARTUPINFOW startup = {sizeof(startup)};
    PROCESS_INFORMATION process = {0};
    BOOL wait_mode = argc == 5 && wcscmp(argv[1], L"--slice") == 0
        && wcscmp(argv[2], L"--wait") == 0;
    if (wait_mode) { argv += 2; argc -= 2; }
    if (argc == 4 && wcscmp(argv[1], L"--slice") == 0) { ++argv; --argc; }
    if (argc != 3) return 101;
    if (OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &token)) {
        CloseHandle(token);
        return 102;
    }
    if (GetLastError() != ERROR_NO_TOKEN) return 103;
    swprintf_s(original, 32768, L"%s\\neutral-original.txt", argv[1]);
    swprintf_s(alias, 32768, L"%s\\link.txt", argv[2]);
    swprintf_s(destination, 32768, L"%s\\moved.txt", argv[2]);
    file = CreateFileW(original, GENERIC_WRITE, 7, NULL, TRUNCATE_EXISTING, 0, NULL);
    if (file != INVALID_HANDLE_VALUE) { CloseHandle(file); return 104; }
    if (SetFileAttributesW(original, FILE_ATTRIBUTE_READONLY)) return 105;
    if (CreateHardLinkW(alias, original, NULL)) return 106;
    if (MoveFileExW(original, destination, 0)) return 107;
    if (DeleteFileW(original)) return 108;
    swprintf_s(destination, 32768, L"%s\\new.txt", argv[1]);
    file = CreateFileW(destination, GENERIC_WRITE, 7, NULL, CREATE_NEW, 0, NULL);
    if (file != INVALID_HANDLE_VALUE) { CloseHandle(file); return 109; }
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            L"D:(A;;FA;;;WD)", SDDL_REVISION_1, &descriptor, NULL)) return 110;
    if (!GetSecurityDescriptorDacl(descriptor, &present, &acl, &defaulted)) return 111;
    written = SetNamedSecurityInfoW(original, SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
        NULL, NULL, acl, NULL);
    LocalFree(descriptor);
    if (written == ERROR_SUCCESS) return 112;
    file = CreateFileW(original, MAXIMUM_ALLOWED, 7, NULL, OPEN_EXISTING, 0, NULL);
    if (file != INVALID_HANDLE_VALUE) {
        BOOL changed = WriteFile(file, "forbidden", 9, &written, NULL);
        CloseHandle(file);
        if (changed) return 113;
    }
    swprintf_s(destination, 32768, L"%s\\allowed.txt", argv[2]);
    file = CreateFileW(destination, GENERIC_WRITE, 7, NULL, CREATE_NEW, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return 114;
    if (!WriteFile(file, "allowed", 7, &written, NULL) || written != 7) {
        CloseHandle(file); return 115;
    }
    CloseHandle(file);
    if (wait_mode) {
        swprintf_s(child, 32768,
            L"cmd.exe /d /v:off /c \"(echo child)>\"%s\\child.txt\" & for /L %%i in (1,1,2147483647) do @rem\"",
            argv[2]);
        if (!CreateProcessW(NULL, child, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                NULL, argv[2], &startup, &process)) return 118;
        CloseHandle(process.hThread);
        WaitForSingleObject(process.hProcess, INFINITE);
        CloseHandle(process.hProcess);
        return 119;
    }
    swprintf_s(child, 32768,
        L"cmd.exe /d /v:off /c \"(echo forbidden)>\"%s\" & del /q \"%s\" & (echo child)>\"%s\\child.txt\" & exit /b 0\"",
        original, original, argv[2]);
    if (!CreateProcessW(NULL, child, NULL, NULL, FALSE, CREATE_NO_WINDOW,
            NULL, argv[2], &startup, &process)) return 116;
    if (WaitForSingleObject(process.hProcess, 10000) != WAIT_OBJECT_0) {
        CloseHandle(process.hThread); CloseHandle(process.hProcess); return 117;
    }
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    return 0;
}

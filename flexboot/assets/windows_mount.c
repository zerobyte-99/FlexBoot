/* SPDX-License-Identifier: GPL-3.0-or-later
 * Read-only ISO attachment for FlexBoot's prepared WinPE environments.
 * Resolve the returned device itself; never select an unrelated new drive.
 */
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <winioctl.h>
#include <virtdisk.h>
#include <stdio.h>
#include <wchar.h>

typedef DWORD (WINAPI *open_fn)(PVIRTUAL_STORAGE_TYPE, PCWSTR, VIRTUAL_DISK_ACCESS_MASK,
 OPEN_VIRTUAL_DISK_FLAG, POPEN_VIRTUAL_DISK_PARAMETERS, PHANDLE);
typedef DWORD (WINAPI *attach_fn)(HANDLE, PSECURITY_DESCRIPTOR, ATTACH_VIRTUAL_DISK_FLAG,
 ULONG, PATTACH_VIRTUAL_DISK_PARAMETERS, LPOVERLAPPED);
typedef DWORD (WINAPI *path_fn)(HANDLE, PULONG, PWSTR);
typedef DWORD (WINAPI *detach_fn)(HANDLE, DETACH_VIRTUAL_DISK_FLAG, ULONG);

static int number(PCWSTR path, STORAGE_DEVICE_NUMBER *value) {
 HANDLE device = CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             NULL, OPEN_EXISTING, 0, NULL);
 if (device == INVALID_HANDLE_VALUE) return 0;
 DWORD size;
 BOOL ok = DeviceIoControl(device, IOCTL_STORAGE_GET_DEVICE_NUMBER, NULL, 0,
                           value, sizeof(*value), &size, NULL);
 CloseHandle(device);
 return ok && size == sizeof(*value);
}

int wmain(int argc, wchar_t **argv) {
 if (argc != 3 || (wcscmp(argv[1], L"mount") && wcscmp(argv[1], L"detach"))) {
  fwprintf(stderr, L"Usage: flexboot-win mount|detach ISO_PATH\n"); return 2;
 }
 DWORD attributes = GetFileAttributesW(argv[2]);
 if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) {
  fwprintf(stderr, L"ISO must be a local regular file: %lu\n", GetLastError()); return 3;
 }
 HMODULE library = LoadLibraryExW(L"virtdisk.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
 if (!library) { fwprintf(stderr, L"virtdisk unavailable: %lu\n", GetLastError()); return 4; }
 open_fn open = (open_fn)GetProcAddress(library, "OpenVirtualDisk");
 attach_fn attach = (attach_fn)GetProcAddress(library, "AttachVirtualDisk");
 path_fn physical = (path_fn)GetProcAddress(library, "GetVirtualDiskPhysicalPath");
 detach_fn detach = (detach_fn)GetProcAddress(library, "DetachVirtualDisk");
 if (!open || !attach || !physical || !detach) { FreeLibrary(library); return 5; }
 VIRTUAL_STORAGE_TYPE type = {VIRTUAL_STORAGE_TYPE_DEVICE_ISO,
  {0xec984aec,0xa0f9,0x47e9,{0x90,0x1f,0x71,0x41,0x5a,0x66,0x34,0x5b}}};
 OPEN_VIRTUAL_DISK_PARAMETERS parameters = {0};
 parameters.Version = OPEN_VIRTUAL_DISK_VERSION_1; parameters.Version1.RWDepth = 1;
 HANDLE handle = NULL;
 DWORD result = open(&type, argv[2], VIRTUAL_DISK_ACCESS_READ,
                     OPEN_VIRTUAL_DISK_FLAG_NONE, &parameters, &handle);
 if (result) { fwprintf(stderr,L"OpenVirtualDisk: %lu\n",result);FreeLibrary(library);return 6; }
 if (!wcscmp(argv[1],L"detach")) {
  HWND console=GetConsoleWindow();if(console)ShowWindow(console,SW_RESTORE);
  result = detach(handle, DETACH_VIRTUAL_DISK_FLAG_NONE, 0);
  if (result) fwprintf(stderr,L"DetachVirtualDisk: %lu\n",result);
  CloseHandle(handle);FreeLibrary(library);return result ? 7 : 0;
 }
 ATTACH_VIRTUAL_DISK_PARAMETERS attachment = {0};attachment.Version=ATTACH_VIRTUAL_DISK_VERSION_1;
 result = attach(handle, NULL, ATTACH_VIRTUAL_DISK_FLAG_READ_ONLY |
                 ATTACH_VIRTUAL_DISK_FLAG_PERMANENT_LIFETIME, 0, &attachment, NULL);
 if (result) { fwprintf(stderr,L"AttachVirtualDisk: %lu\n",result);CloseHandle(handle);FreeLibrary(library);return 8; }
 for (int attempt=0;attempt<200;attempt++) {
  wchar_t physical_path[1024];ULONG bytes=sizeof(physical_path);
  STORAGE_DEVICE_NUMBER expected;
  if (!physical(handle,&bytes,physical_path) && number(physical_path,&expected) && expected.DeviceType == FILE_DEVICE_CD_ROM) {
   int selected = -1;DWORD drives=GetLogicalDrives();
   for (int bit=0;bit<26;bit++) if (drives & (1u<<bit)) {
    wchar_t volume[]=L"\\\\.\\A:";volume[4]=(wchar_t)(L'A'+bit);
    STORAGE_DEVICE_NUMBER actual;
    if (number(volume,&actual) && actual.DeviceType == expected.DeviceType && actual.DeviceNumber == expected.DeviceNumber) {
     if (selected != -1) { selected=-2;break; }
     selected=bit;
    }
   }
   if (selected >= 0) {
    wprintf(L"%lc:\n",(wchar_t)(L'A'+selected));
    /* This child shares the startup console. Keep it from covering Setup. */
    HWND console=GetConsoleWindow();if(console)ShowWindow(console,SW_MINIMIZE);
    CloseHandle(handle);FreeLibrary(library);return 0;
   }
   if (selected == -2) break;
  }
  Sleep(100);
 }
 fwprintf(stderr,L"Cannot uniquely map the requested ISO's CD-ROM device\n");
 result=detach(handle,DETACH_VIRTUAL_DISK_FLAG_NONE,0);
 if(result) fwprintf(stderr,L"Cleanup detach failed: %lu\n",result);
 CloseHandle(handle);FreeLibrary(library);return 9;
}

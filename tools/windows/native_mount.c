/* SPDX-License-Identifier: GPL-3.0-or-later
 * Experimental read-only ISO API probe for disposable WinPE guests.
 * Not installed or invoked by FlexBoot. See docs/WINDOWS-EXPERIMENTS.md.
 */
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <virtdisk.h>
#include <stdio.h>

typedef DWORD (WINAPI *open_fn)(PVIRTUAL_STORAGE_TYPE,PCWSTR,VIRTUAL_DISK_ACCESS_MASK,
                              OPEN_VIRTUAL_DISK_FLAG,POPEN_VIRTUAL_DISK_PARAMETERS,PHANDLE);
typedef DWORD (WINAPI *attach_fn)(HANDLE,PSECURITY_DESCRIPTOR,ATTACH_VIRTUAL_DISK_FLAG,
                                ULONG,PATTACH_VIRTUAL_DISK_PARAMETERS,LPOVERLAPPED);

int wmain(int argc, wchar_t **argv) {
    if (argc != 2) { fwprintf(stderr,L"Supply an ISO pathname\n");return 2; }
    HMODULE library = LoadLibraryExW(L"virtdisk.dll",NULL,LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!library) { fwprintf(stderr,L"virtdisk.dll unavailable: %lu\n",GetLastError());return 3; }
    open_fn open = (open_fn)GetProcAddress(library,"OpenVirtualDisk");
    attach_fn attach = (attach_fn)GetProcAddress(library,"AttachVirtualDisk");
    if (!open || !attach) { fwprintf(stderr,L"Virtual disk API unavailable\n");return 4; }
    VIRTUAL_STORAGE_TYPE type = {VIRTUAL_STORAGE_TYPE_DEVICE_ISO,
        {0xec984aec,0xa0f9,0x47e9,{0x90,0x1f,0x71,0x41,0x5a,0x66,0x34,0x5b}}};
    OPEN_VIRTUAL_DISK_PARAMETERS parameters = {0};
    parameters.Version = OPEN_VIRTUAL_DISK_VERSION_1;
    parameters.Version1.RWDepth = 1;
    HANDLE handle = NULL;
    DWORD before = GetLogicalDrives();
    DWORD result = open(&type,argv[1],VIRTUAL_DISK_ACCESS_READ,
                        OPEN_VIRTUAL_DISK_FLAG_NONE,&parameters,&handle);
    if (result) { fwprintf(stderr,L"OpenVirtualDisk: %lu\n",result);return 5; }
    ATTACH_VIRTUAL_DISK_PARAMETERS attachment = {0};
    attachment.Version = ATTACH_VIRTUAL_DISK_VERSION_1;
    result = attach(handle,NULL,ATTACH_VIRTUAL_DISK_FLAG_READ_ONLY |
                    ATTACH_VIRTUAL_DISK_FLAG_PERMANENT_LIFETIME,0,&attachment,NULL);
    if (result) { fwprintf(stderr,L"AttachVirtualDisk: %lu\n",result);CloseHandle(handle);return 6; }
    for (int attempt=0;attempt<100;attempt++) {
        DWORD added=GetLogicalDrives() & ~before;
        int selected = -1;
        for(int bit=0;bit<26;bit++) if(added & (1u << bit)) {
            wchar_t root[] = L"A:\\";
            root[0]=(wchar_t)(L'A'+bit);
            if(GetDriveTypeW(root)==DRIVE_CDROM) {
                if (selected != -1) {
                    fwprintf(stderr,L"Ambiguous CD-ROM enumeration\n");
                    CloseHandle(handle);return 8;
                }
                selected = bit;
            }
        }
        if (selected != -1) {
            wprintf(L"%lc:\n",(wchar_t)(L'A'+selected));
            CloseHandle(handle);return 0;
        }
        Sleep(100);
    }
    fwprintf(stderr,L"ISO attached but no new CD-ROM drive letter appeared\n");
    CloseHandle(handle);return 7;
}

// OpenCrawlerLauncher —— 极小的 Win32 GUI 启动器（零控制台、零依赖）。
//
// 优先级：
//   1. 同目录 OpenCrawlerLab.exe（PyInstaller 打包的完整独立程序）
//   2. pythonw.exe / python.exe + desktop/launcher.py（源码运行）
//
// 编译（MinGW-w64）：
//   g++ -O2 -s -mwindows win_launcher.cpp -o OpenCrawlerLauncher.exe
//
// 打包后的 exe 与源码启动器都只是「打开桌面窗口」，不含任何爬虫逻辑，
// 因此即使不重新编译 C++，Python 侧升级也会立即生效。
#include <windows.h>

#include <string>
#include <vector>

static std::wstring ExeDir() {
    std::vector<wchar_t> buf(MAX_PATH * 4, L'\0');
    GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
    std::wstring path(buf.data());
    const size_t pos = path.find_last_of(L"\\/");
    return pos == std::wstring::npos ? std::wstring(L".") : path.substr(0, pos);
}

static std::wstring BaseName(const std::wstring& path) {
    const size_t pos = path.find_last_of(L"\\/");
    return pos == std::wstring::npos ? path : path.substr(pos + 1);
}

static bool Start(const std::wstring& exe, const std::wstring& args, const std::wstring& dir) {
    std::vector<wchar_t> cmd(args.begin(), args.end());
    cmd.push_back(L'\0');
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    const BOOL ok = CreateProcessW(
        exe.c_str(), cmd.data(), nullptr, nullptr, FALSE,
        CREATE_NO_WINDOW, nullptr, dir.c_str(), &si, &pi);
    if (!ok) return false;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return true;
}

static bool Exists(const std::wstring& path) {
    return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    const std::wstring dir = ExeDir();

    // 1) 完整打包版
    const std::wstring packed = dir + L"\\OpenCrawlerLab.exe";
    if (Exists(packed) && Start(packed, L"", dir)) {
        return 0;
    }

    // 2) 源码运行：找 Python 解释器
    const std::wstring script = dir + L"\\desktop\\launcher.py";
    if (!Exists(script)) {
        MessageBoxW(nullptr,
            L"未找到 OpenCrawlerLab.exe，也未找到 desktop\\launcher.py。\n"
            L"请把本启动器放在项目根目录，或先运行 desktop\\build_exe.py。",
            L"OpenCrawlerLab 启动失败", MB_ICONERROR | MB_OK);
        return 1;
    }
    const wchar_t* candidates[] = {
        L"pythonw.exe", L"python.exe",
        L"C:\\Windows\\pyw.exe", L"C:\\Windows\\py.exe",
    };
    for (const wchar_t* name : candidates) {
        std::wstring args = std::wstring(L"\"") + name + L"\" \"" + script + L"\"";
        if (Start(name, args, dir)) return 0;
    }
    MessageBoxW(nullptr,
        L"找不到 Python 解释器。\n请安装 Python 3.11+ 并加入 PATH，"
        L"或先运行 desktop\\build_exe.py 生成独立 exe。",
        L"OpenCrawlerLab 启动失败", MB_ICONERROR | MB_OK);
    return 1;
}

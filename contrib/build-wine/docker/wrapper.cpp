#include <cstdlib>
#include <cctype>
#include <iostream>
#include <string>
#include <string_view>
#include <utility>

#include <windows.h>

namespace {
    template <typename Func>
    struct Defer {
        Func f;
        Defer(Func&& f_) : f{ std::move(f_) } {}
        ~Defer() { f(); }
    };

    std::string ReplaceCommandAndPrependArg(std::string_view commandLine, const std::string& newCmd,
                                            const std::string& arg, const std::string& argPost)
    {
        bool in_quot{}, in_bs{};
        std::string_view::size_type pos{};
        for (; pos < commandLine.size(); ++pos) {
            const char ch = commandLine[pos];
            if (ch == ' ' && !in_quot && !in_bs) break;
            else if (ch == '\\' && in_quot) in_bs = !in_bs;
            else if (ch == '"' && !in_bs) in_quot = !in_quot;
            else if (in_bs) in_bs = false;
        }
        return newCmd + " " + arg + std::string{commandLine.substr(pos)} + " " + argPost;
    }

    std::string GetErrorMessage(DWORD dwErrorCode)
    {
        LPSTR psz = nullptr;
        const DWORD cchMsg = FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS
                                            | FORMAT_MESSAGE_ALLOCATE_BUFFER,
                                            NULL, // (not used with FORMAT_MESSAGE_FROM_SYSTEM)
                                            dwErrorCode,
                                            MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
                                            reinterpret_cast<LPSTR>(&psz),
                                            0,
                                            NULL);
        if (cchMsg > 0)
        {
            // Delete psz on scope end (in case std::string c'tor throw)
            Defer d([&psz] { ::HeapFree(::GetProcessHeap(), 0, psz); psz = nullptr; });
            std::string ret(psz, cchMsg);
            while (!ret.empty() && std::isspace(ret.back())) ret.pop_back(); // delete trailing whitespace
            return ret;
        }
        else
        {
            return "Error code (" + std::to_string(dwErrorCode) + ")";
        }
    }
} // end namespace

int main()
{
    const char* const prog = PROG;
    const char* const arg = ARG;
    const char* const argPost = ARG_POST;
    std::string cmdBuf = ReplaceCommandAndPrependArg(GetCommandLineA(), prog, arg, argPost);
    //std::cerr << "Old: [" << GetCommandLineA() << "]" << std::endl;
    //std::cerr << "New: [" << cmdBuf << "]" << std::endl;

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    // Start the child process.
    if (!CreateProcessA(NULL,          // No module name (use command line)
                        cmdBuf.data(), // Command line
                        NULL,          // Process handle not inheritable
                        NULL,          // Thread handle not inheritable
                        FALSE,         // Set handle inheritance to FALSE
                        0,             // No creation flags
                        NULL,          // Use parent's environment block
                        NULL,          // Use parent's starting directory
                        &si,           // Pointer to STARTUPINFO structure
                        &pi)           // Pointer to PROCESS_INFORMATION structure
        )
    {
        std::cerr << "CreateProcess failed for \"" << prog << "\": " << GetErrorMessage(GetLastError()) << std::endl;
        return EXIT_FAILURE;
    }

    // Wait until child process exits.
    WaitForSingleObject(pi.hProcess, INFINITE);

    Defer d([&pi] {
        // Close process and thread handles.
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    });

    DWORD exit_code;
    if (!GetExitCodeProcess(pi.hProcess, &exit_code)) {
        std::cerr << "Could not retrieve exit code for subprocess: " << GetErrorMessage(GetLastError()) << std::endl;
        return EXIT_FAILURE;
    }

    ExitProcess(exit_code); // propagate the exit code up to caller

    return EXIT_SUCCESS; // not reached
}

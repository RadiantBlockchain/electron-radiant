@echo off

set VCYEAR=2019
set VCDIR=c:\Program Files\Microsoft Visual Studio\%VCYEAR%\BuildTools\VC

call "%VCDIR%\Auxiliary\Build\vcvarsall.bat" x86

set LINK_PATH=%VCToolsInstallDir%\bin\Hostx86\x86\link.exe
set LINK_REAL=%VCToolsInstallDir%\bin\Hostx86\x86\link_real.exe
set LINK_REAL_ESC=\\\"%LINK_REAL:\=\\%\\\"

cl /nologo /std:c++17 /Fe:C:\link.exe "/DPROG=\"%LINK_REAL_ESC%\"" "/DARG=\"/Brepro /emittoolversioninfo:no /emitpogophaseinfo\"" "/DARG_POST=\"\"" /EHsc C:\wrapper.cpp /link /Brepro

set CL_PATH=%VCToolsInstallDir%\bin\Hostx86\x86\cl.exe
set CL_REAL=%VCToolsInstallDir%\bin\Hostx86\x86\cl_real.exe
set CL_REAL_ESC=\\\"%CL_REAL:\=\\%\\\"

cl /nologo /std:c++17 /Fe:C:\cl.exe "/DPROG=\"%CL_REAL_ESC%\"" "/DARG=\"/Brepro\"" "/DARG_POST=\"/link /emittoolversioninfo:no /emitpogophaseinfo\"" /EHsc C:\wrapper.cpp /link /Brepro

move "%LINK_PATH%" "%LINK_REAL%"
move "C:\link.exe" "%LINK_PATH%"

move "%CL_PATH%" "%CL_REAL%"
move "C:\cl.exe" "%CL_PATH%"

exit 0

!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "Pirate Cinema"
OutFile "pirate-cinema-installer.exe"
InstallDir "$LOCALAPPDATA\Programs\Pirate Cinema"
RequestExecutionLevel user
SetCompressor /SOLID lzma

!define MUI_WELCOMEPAGE_TEXT "Welcome to Pirate Cinema setup."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"

Section "Pirate Cinema" SEC_APP
  ; Stop app if running
  nsExec::Exec '"$SYSDIR\taskkill.exe" /IM "Pirate Cinema.exe" /T /F'
  Sleep 700

  SetOutPath "$INSTDIR"
  File /r "dist\Pirate Cinema\*"
  
  WriteUninstaller "$INSTDIR\Uninstall Pirate Cinema.exe"

  CreateShortcut "$SMPROGRAMS\Pirate Cinema.lnk" "$INSTDIR\Pirate Cinema.exe"
  CreateShortcut "$DESKTOP\Pirate Cinema.lnk" "$INSTDIR\Pirate Cinema.exe"
SectionEnd

Section "Uninstall"
  nsExec::Exec '"$SYSDIR\taskkill.exe" /IM "Pirate Cinema.exe" /T /F'
  Sleep 700
  Delete "$SMPROGRAMS\Pirate Cinema.lnk"
  Delete "$DESKTOP\Pirate Cinema.lnk"
  RMDir /r "$INSTDIR"
SectionEnd

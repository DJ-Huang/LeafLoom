; Override the builder's default check, which can forcibly kill active writers.
!macro customCheckAppRunning
  ${If} ${FileExists} "$INSTDIR\VaultRag.exe"
    !ifdef BUILD_UNINSTALLER
      ${If} ${isUpdated}
        nsExec::ExecToStack '"$INSTDIR\VaultRag.exe" --prepare-update'
      ${Else}
        nsExec::ExecToStack '"$INSTDIR\VaultRag.exe" --prepare-uninstall'
      ${EndIf}
    !else
      nsExec::ExecToStack '"$INSTDIR\VaultRag.exe" --prepare-update'
    !endif
    Pop $0
    Pop $1
    ${If} $0 != 0
      MessageBox MB_OK "请在本地知识库处理未保存内容并正常退出，再更新或卸载。"
      Abort
    ${EndIf}
  ${EndIf}
!macroend

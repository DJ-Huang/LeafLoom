# Tunnel で ChatGPT と接続する

## できること

許可したローカル機能を ChatGPT に接続します。

## 始める前に

既存の Tunnel ID と Tunnels Read + Use 権限の Runtime App Key を用意します。鍵をメモに保存しないでください。

## 操作手順

1. デスクトップの設定から AI 接続、ChatGPT 接続を開きます。
2. ID と App Key を入力し、保存して接続します。実行環境は同梱されています。
3. 準備後、ChatGPT のカスタム MCP で Tunnel・同じ ID・No authentication を選び、会話で有効にします。
4. LeafLoom 側でメモ・Feishu の読み取りと必要な書き込みを個別に許可します。
5. 架空資料で実際に呼び出し、権限と結果を確認します。

## 完了後の状態

トレイに残る間は接続を維持し、終了で停止します。準備完了だけでは呼び出し成功を意味しません。

## うまくいかないとき

共有設定につき受管インスタンスは 1 件にします。権限変更後はツールを更新します。切断すると自動接続も無効になります。

## 次のステップ

- [MCP 権限と認証情報を管理する](permissions.md)
- [ローカル MCP クライアントと Skill を接続する](mcp.md)
- [AI・MCP・Tunnel・Feishu の接続を調べる](connection-problems.md)

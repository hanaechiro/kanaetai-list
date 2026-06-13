# 叶えたいことリスト 開発メモ

## スマホ実機で確認する手順

PCとスマホを同じWi-Fiに接続してから、Django開発サーバーを外部端末から見える形で起動します。

```powershell
py manage.py runserver 0.0.0.0:8001
```

別のPowerShellで、PCのIPアドレスを確認します。

```powershell
ipconfig
```

表示された `IPv4 アドレス` を確認してください。例：

```text
IPv4 アドレス . . . . . . . . . . . .: 192.168.1.23
```

スマホのブラウザで、次のようにアクセスします。

```text
http://192.168.1.23:8001/
```

`192.168.1.23` の部分は、自分のPCで確認したIPv4アドレスに置き換えてください。

## Windows Defender ファイアウォール

初回アクセス時、Windows Defender ファイアウォールで Python の通信許可を求められる場合があります。

スマホからアクセスできない場合は、以下を確認してください。

- PCとスマホが同じWi-Fiに接続されている
- `py manage.py runserver 0.0.0.0:8001` で起動している
- Windows Defender ファイアウォールで Python の通信が許可されている
- URLのIPアドレスとポート番号が正しい


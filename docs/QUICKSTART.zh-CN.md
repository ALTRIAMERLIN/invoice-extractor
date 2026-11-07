# 中文启动说明

> 个人演示项目。发票全部是虚构数据，不是客户案例。

下面的命令都在 Windows PowerShell 里运行。

## 1. 需要的软件

| 软件 | 用途 | 说明 |
|---|---|---|
| Python 3.11 | 运行程序 | 验证目标是 Windows 上的 Python 3.11 |
| Git | 下载代码 | 也可以在 GitHub 页面点 Code → Download ZIP |

程序在本机处理 PDF，不需要外部 AI 服务或 API 密钥。

## 2. 安装（只做一次）

```powershell
git clone https://github.com/ALTRIAMERLIN/invoice-extractor.git
cd invoice-extractor
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

之后的命令都在 `invoice-extractor` 文件夹里运行，直接调用 `.venv` 里的 Python，不用激活虚拟环境。

## 3. 打开网页界面

```powershell
.\.venv\Scripts\python -m streamlit run app.py
```

也可以运行 `run.ps1`。看到本地地址后，用浏览器打开 http://127.0.0.1:8501。程序只绑定本机，别的电脑访问不到。要停止，就在这个 PowerShell 窗口按 `Ctrl+C`。

页面上的流程：

1. 上传一批带文字层的英文 PDF，或载入三张自带的虚构示例发票。
2. 查看批次表。打开一条记录，看问题、候选文本和页码。
3. 保存修改。改动一条已确认的记录后，旧的确认会取消。原始抽取结果仍然保留。
4. 确认修改后的记录。原来有问题，或仍有异常时，需要填写原因。无效数值不能确认。
5. 选择导出范围，确认后下载 Excel 和 CSV。两个文件来自同一次最终数据。

自动检查是规则，不是准确率保证。用于付款或记账前，对照原始发票核对。

## 4. 演示视频

`video\out\invoice-extractor-demo.mp4`：67 秒，1920×1080，60 帧，H.264。声音只有模板自带的界面音效，没有旁白，也没有音乐。画面来自本机程序的真实操作。英文说明、校验结果和已知限制见 [README.md](../README.md) 的 Demo video，细节在 `video\README.md`。

## 5. 运行测试

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
```

## 6. 常见问题

| 现象 | 解决办法 |
|---|---|
| 提示 `py` 不是内部或外部命令 | 安装 Python 3.11，或把命令里的 `py -3.11` 换成已加入 PATH 的 `python` |
| 端口 8501 被占用 | 在启动命令最后加 `--server.port 8502`，再打开 http://127.0.0.1:8502 |
| 扫描件、手写发票没有结果 | 这一版没有 OCR，需要手工处理 |
| 刷新或重启后批次消失 | 上传的 PDF 和复核状态只放在当前内存会话里，程序不故意保存批次 |
| 货币只有 `$` | 不猜测币种。需要发票上写明 USD、EUR、GBP、HKD 或 CNY |

更多说明见英文 [README.md](../README.md)。

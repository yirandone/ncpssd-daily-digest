# ncpssd-daily-digest

> 新闻传播学每日文献推送工具。  
> 从国家哲学社会科学文献中心（NCPSSD）检索指定期刊与主题词，使用 DeepSeek 生成推荐理由，并发送 HTML 邮件。

## 功能

- 按期刊和主题词检索文献
- 每日推荐 3 篇，自动去重
- 候选不足时自动放宽时间范围
- DeepSeek 生成推荐理由
- QQ 邮箱发送 HTML 简报
- 本地保存每日推送结果
- 支持 `--dry-run` 预览

## 快速开始

安装依赖：

```powershell
pip install requests python-dotenv
```

创建 `.env` 并填写配置：

```ini
DEEPSEEK_API_KEY=你的DeepSeek密钥
QQ_EMAIL=你的QQ邮箱@qq.com
QQ_SMTP_CODE=你的QQ邮箱SMTP授权码
```

运行：

```powershell
python daily_digest.py
```

预览结果但不发送邮件：

```powershell
python daily_digest.py --dry-run
```

不调用 DeepSeek 的预览：

```powershell
python daily_digest.py --dry-run --skip-deepseek
```

## 配置

在 `daily_digest.py` 顶部修改目标期刊、关键词和每日推送数量：

```python
JOURNALS = [
    "国际新闻界",
    "新闻与传播研究",
    "现代传播",
    "新闻大学",
]

TOPICS = [
    "算法审计",
    "多模态新闻",
    "AI说服",
]

RESULT_COUNT = 3
```

多个主题词是“或”关系。增加关键词可扩大候选范围，但可能降低相关性。

## 文件说明

```text
daily_digest.py       # 主脚本
test_ncpssd.py        # NCPSSD 接口测试
.env.example          # 配置模板
pushed.txt            # 已推送标题记录，自动生成
digest_output/        # 每日 HTML 简报，自动生成
```

## 注意事项

- `.env` 中包含 API Key 和 QQ SMTP 授权码，不要提交到 GitHub。
- `QQ_SMTP_CODE` 是 QQ 邮箱 SMTP 授权码，不是 QQ 密码。
- NCPSSD 响应较慢时，可提高 `REQUEST_TIMEOUT_SECONDS` 或降低 `POOL_SIZE`。
- 本项目仅用于个人、低频的文献发现与整理，不下载论文全文。

## 致谢

- 文献元数据来源：[国家哲学社会科学文献中心](https://www.ncpssd.org/)
- 推荐理由由 [DeepSeek](https://www.deepseek.com/) 提供
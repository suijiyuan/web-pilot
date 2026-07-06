# web-pilot

`web-pilot` 是一个基于 Playwright 的 Python CLI。它通过 JSON 计划文件定义浏览器配置、上下文、变量和测试步骤，并按顺序执行自动化 Web 测试。

当前实现使用 `p.chromium.launch(...)` 启动浏览器，因此适合搭配 `chromium`、`chrome`、`msedge` 等 Chromium 内核通道使用。

## 安装

项目当前只有一个运行时依赖：

```bash
.conda/bin/python -m pip install -r requirements.txt
```

安装 Playwright 浏览器：

```bash
.conda/bin/python -m playwright install chromium
```

如果你希望使用 Chrome 或 Edge 通道，也可以额外安装对应浏览器，并在计划文件或命令行里指定 `--channel`。

## 快速开始

列出计划中的测试：

```bash
.conda/bin/python -m web_pilot list --plan examples/demo_plan.json
```

运行整个计划并保存 Trace：

```bash
.conda/bin/python -m web_pilot run --plan examples/demo_plan.json --trace
```

按名称只运行单个测试：

```bash
.conda/bin/python -m web_pilot run --plan examples/demo_plan.json --only bing_search
```

覆盖计划内变量：

```bash
.conda/bin/python -m web_pilot run \
  --plan examples/demo_plan.json \
  --var KEYWORD=Playwright \
  --var BASE_URL=https://www.bing.com
```

当步骤里的 `url` 以 `/` 开头时，可以通过 `--base-url` 拼接完整地址：

```bash
.conda/bin/python -m web_pilot run \
  --plan examples/demo_plan.json \
  --base-url https://example.com
```

## CLI

顶层命令：

```bash
.conda/bin/python -m web_pilot --help
```

```text
usage: web-pilot [-h] {run,list} ...
```

### `list`

```bash
.conda/bin/python -m web_pilot list --help
```

```text
usage: web-pilot list [-h] --plan PLAN [--var VAR]
```

参数说明：

- `--plan PLAN`：计划文件路径
- `--var KEY=VALUE`：为计划插值变量，支持重复传入

### `run`

```bash
.conda/bin/python -m web_pilot run --help
```

```text
usage: web-pilot run [-h] --plan PLAN [--base-url BASE_URL] [--headed]
                     [--headless] [--channel CHANNEL] [--trace]
                     [--timeout-ms TIMEOUT_MS] [--only ONLY] [--var VAR]
```

参数说明：

- `--plan PLAN`：计划文件路径
- `--base-url BASE_URL`：用于补全以 `/` 开头的 `goto.url`
- `--headed`：强制有头模式
- `--headless`：强制无头模式
- `--channel CHANNEL`：覆盖计划中的浏览器通道，如 `chromium`、`chrome`、`msedge`
- `--trace`：为每个测试保存 `trace.zip`
- `--timeout-ms TIMEOUT_MS`：页面操作与断言默认超时，单位毫秒，默认 `30000`
- `--only ONLY`：只运行指定测试名，可重复传入
- `--var KEY=VALUE`：覆盖计划里的变量插值，可重复传入

退出码：

- `0`：全部测试通过
- `1`：存在失败测试
- `2`：计划文件格式错误、参数错误等 `PlanError`

## 产物目录

执行 `run` 后，测试产物默认写入：

```text
artifacts/<plan.name>/<test.name>/
```

当前实现会生成这些文件：

- `trace.zip`：启用 `--trace` 时生成
- `failure.png`：测试失败时自动截取整页截图
- 自定义截图：`screenshot` 步骤中的 `path`

说明：

- `screenshot.path` 如果是相对路径，会被解析到当前测试产物目录下
- `test.name` 中的 `/` 会在目录名里被替换成 `_`

## 计划文件结构

计划文件必须是一个 JSON 对象，最常见结构如下：

```json
{
  "name": "demo",
  "artifactsDir": "artifacts",
  "vars": {
    "BASE_URL": "https://www.bing.com/",
    "KEYWORD": "蜜雪冰城"
  },
  "browser": {
    "channel": "chromium",
    "headless": false,
    "slowMoMs": 0,
    "args": []
  },
  "context": {
    "viewport": { "width": 1280, "height": 720 }
  },
  "tests": [
    {
      "name": "bing_search",
      "steps": [
        { "action": "goto", "url": "${BASE_URL}/search?q=${KEYWORD}", "waitUntil": "commit" },
        { "action": "wait", "ms": 5000 },
        { "action": "screenshot", "path": "bing_search.png", "fullPage": true }
      ]
    }
  ]
}
```

### 顶层字段

- `name`：计划名称，缺省时取 JSON 文件名
- `artifactsDir`：产物根目录，默认 `artifacts`
- `vars`：字符串到字符串的映射，支持 `${VAR_NAME}` 插值
- `browser`：浏览器启动配置
- `context`：浏览器上下文配置
- `tests`：测试数组，不能为空

### `browser`

- `channel`：浏览器通道，默认 `chromium`
- `headless`：是否无头运行，默认 `true`
- `slowMoMs`：每步慢动作延迟，默认 `0`
- `args`：启动浏览器时附带的参数数组

### `context`

- `viewport`：页面视口，需包含整数 `width` 和 `height`
- `storageState`：Playwright `storage_state` 文件路径
- `userAgent`：自定义 UA
- `locale`：语言区域
- `timezoneId`：时区 ID

### `tests`

- `tests[].name`：测试名称，必填
- `tests[].steps`：步骤数组，不能为空
- `tests[].steps[].action`：步骤类型，必填
- 除 `action` 外的其它字段都会作为该步骤的参数传入执行器

## 变量插值

当前实现会先读取计划里的 `vars`，再用命令行 `--var` 覆盖，然后对整个 JSON 做字符串插值。

例如：

```json
{
  "vars": {
    "KEYWORD": "Playwright"
  },
  "tests": [
    {
      "name": "search",
      "steps": [
        { "action": "goto", "url": "https://www.bing.com/search?q=${KEYWORD}" }
      ]
    }
  ]
}
```

如果变量不存在，当前实现会保留原始占位符，不会报错。

## 内置 Action

### 页面与交互

- `goto`：`url` 必填，支持可选 `waitUntil`
- `click`：`selector` 必填
- `dblclick`：`selector` 必填
- `fill`：`selector`、`text` 必填
- `type`：`selector`、`text` 必填，支持可选 `delayMs`
- `press`：`key` 必填，`selector` 可选；不传 `selector` 时发送到键盘对象
- `set_viewport`：`width`、`height` 必填
- `evaluate`：`expression` 必填

### 等待与断言

- `wait_for_selector`：`selector` 必填，`state` 可选，默认 `visible`
- `wait`：`ms` 必填
- `expect_visible`：`selector` 必填
- `expect_hidden`：`selector` 必填
- `expect_text`：`selector`、`text` 必填，`contains` 可选
- `expect_title`：`text` 必填，`contains` 可选
- `expect_url`：`text` 必填，`contains` 可选

### 截图

- `screenshot`：`path` 必填，`fullPage` 可选，默认 `false`

## 当前示例

仓库内置示例文件为 `examples/demo_plan.json`，当前行为是：

- 打开 Bing 搜索结果页
- 搜索关键词 `蜜雪冰城`
- 等待 5 秒
- 保存整页截图到 `artifacts/demo/bing_search/bing_search.png`

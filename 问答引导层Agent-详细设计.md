# 问答引导层 Agent 详细设计文档

> 版本：v2.0  
> 日期：2026-04-19  
> 类型：开发文档

---

## 一、Agent 概述

### 1.1 核心定位

问答引导层Agent是老人自传系统的"采访记者"，负责：
- 与老人进行多轮对话，收集人生故事
- 灵活运用多种采访策略，引导老人回忆
- 将碎片化的对话内容归纳整理，传递给下游

**最终目标**：以时间线为轴，从童年到老年收集完整的人生经历

### 1.2 Agent 组成架构

问答引导层由**多个子Agent协作**完成，形成流水线式的异步处理：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        问答引导层 Agent 架构                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │
│   │  对话主控   │ ←→ │  问题生成   │ ←→ │  记忆管理   │               │
│   │  Agent     │    │  Agent     │    │  Agent     │               │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘               │
│          │                  │                  │                       │
│          │                  │                  │                       │
│          ▼                  ▼                  ▼                       │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │
│   │  知识库查询  │    │  内容归纳   │    │  情绪识别   │               │
│   │  Agent     │    │  Agent     │    │  Agent     │               │
│   └─────────────┘    └─────────────┘    └─────────────┘               │
│                                                                         │
│                    ┌─────────────────────────┐                         │
│                    │      多层记忆库         │                         │
│                    │  (短期/长期/画像)       │                         │
│                    └─────────────────────────┘                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 子Agent职责划分

| Agent | 职责 | 触发方式 |
|-------|------|----------|
| **对话主控Agent** | 管理对话流程、状态切换、协调其他Agent | 主循环持续运行 |
| **问题生成Agent** | 根据当前状态和记忆生成下一个问题 | 异步调用 |
| **记忆管理Agent** | 管理三层记忆的读写、更新、检索 | 异步调用 |
| **知识库查询Agent** | 从md文件系统中检索相关内容 | 异步调用 |
| **内容归纳Agent** | 将对话内容整理为结构化信息 | 批量/定时触发 |
| **情绪识别Agent** | 识别老人情绪状态，调整对话策略 | 实时监控 |

---

## 二、异步设计详解

### 2.1 异步流程总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          异步处理流水线                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   用户输入                                                               │
│      │                                                                  │
│      ▼                                                                  │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  并行触发三个异步任务：                                           │  │
│   │                                                                   │  │
│   │  [Task A] 知识库查询 ──→ 查找相关记忆 ──→ 返回相关内容           │  │
│   │                                                                   │  │
│   │  [Task B] 情绪识别 ──→ 分析用户输入 ──→ 返回情绪状态             │  │
│   │                                                                   │  │
│   │  [Task C] 内容归纳 ──→ 提取关键信息 ──→ 更新记忆库               │  │
│   │                                                                   │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│      ▼ (等待所有异步任务完成或超时)                                      │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  问题生成Agent                                                   │  │
│   │  输入：知识库结果 + 情绪状态 + 当前状态 + 对话历史                │  │
│   │  输出：下一个问题                                                 │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│      │                                                                  │
│      ▼                                                                  │
│   返回给用户                                                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 异步任务详细设计

#### Task A: 知识库查询（异步）

```python
# 伪代码示意
async def query_knowledge_base(user_input, current_context):
    """
    异步查询知识库，获取相关记忆
    
    流程：
    1. 从用户输入中提取关键词和实体
    2. 并行查询三层记忆
    3. 合并结果，按相关度排序
    """
    
    # 提取查询关键词
    keywords = extract_keywords(user_input)
    entities = extract_entities(user_input)  # 人名、地名、时间
    
    # 并行查询三层记忆
    results = await asyncio.gather(
        query_short_term_memory(keywords, current_context),
        query_long_term_memory(entities),  # 从md文件系统
        query_profile_memory(entities)     # 画像发散
    )
    
    return merge_and_rank_results(results)
```

#### Task B: 情绪识别（异步）

```python
async def detect_emotion(user_input, conversation_history):
    """
    异步识别用户情绪状态
    
    输出：
    - emotion_type: positive/neutral/negative/mixed
    - emotion_intensity: low/medium/high
    - suggested_action: continue/pause/comfort/redirect
    """
    
    emotion = await emotion_model.analyze(user_input, conversation_history)
    
    # 根据情绪强度决定是否需要特殊处理
    if emotion.intensity == "high" and emotion.type in ["sadness", "anger", "fear"]:
        emotion.suggested_action = "comfort"
    
    return emotion
```

#### Task C: 内容归纳（异步，可延迟）

```python
async def summarize_content(user_input, turn_id):
    """
    异步归纳对话内容，更新记忆库
    
    触发机制：
    - 每轮对话后延迟触发（不阻塞响应）
    - 或累积N轮后批量处理
    """
    
    # 提取结构化信息
    extracted = await extract_structured_info(user_input)
    
    # 更新三层记忆
    await asyncio.gather(
        update_short_term_memory(extracted),
        update_long_term_memory(extracted),  # 写入md文件
        update_profile_memory(extracted)
    )
    
    # 检查是否需要触发传递给下游
    if should_handoff_to_structuring_layer():
        await handoff_to_agent_b(extracted)
```

### 2.3 异步调度策略

| 任务类型 | 优先级 | 超时时间 | 失败策略 |
|----------|--------|----------|----------|
| 情绪识别 | 高 | 3秒 | 默认neutral |
| 知识库查询 | 中 | 5秒 | 使用缓存/跳过 |
| 内容归纳 | 低 | 10秒 | 加入重试队列 |
| 问题生成 | 最高 | 8秒 | 使用默认问题 |

---

## 三、记忆管理系统

### 3.1 三层记忆架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           三层记忆架构                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  短期记忆 (Short-Term Memory)                                    │  │
│   │  ────────────────────────────────────────────────────────────   │  │
│   │  存储：当前对话的上下文                                          │  │
│   │  容量：最近 10-20 轮对话                                         │  │
│   │  更新：每轮对话实时更新                                          │  │
│   │  用途：保持对话连贯性、避免重复提问                               │  │
│   │  存储：内存/Redis                                                │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  长期记忆 (Long-Term Memory)                                     │  │
│   │  ────────────────────────────────────────────────────────────   │  │
│   │  存储：从知识库里找到的直接相关内容                               │  │
│   │  格式：Markdown 文件系统                                         │  │
│   │  内容：已收集的事件、人物、时间线                                 │  │
│   │  更新：内容归纳后写入                                            │  │
│   │  用途：知识库检索、上下文引用                                     │  │
│   │  存储：文件系统 (.md 文件)                                       │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  画像记忆 (Profile Memory)                                       │  │
│   │  ────────────────────────────────────────────────────────────   │  │
│   │  存储：以时间/事件/人物为基点展开的记忆                           │  │
│   │  用途：供大模型发散联想、深度挖掘                                 │  │
│   │  特点：结构化的人物画像和关系网络                                 │  │
│   │  更新：事件确认后更新画像                                        │  │
│   │  存储：JSON + Markdown 混合                                      │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 文件系统式知识库设计

```
memory/
├── events/                    # 事件记忆库
│   ├── childhood/             # 童年事件
│   │   ├── birth-family.md    # 出生家庭
│   │   ├── early-memory.md    # 早期记忆
│   │   └── ...
│   ├── youth/                 # 青年事件
│   ├── middle-age/            # 中年事件
│   └── elderly/               # 老年事件
│
├── people/                    # 人物画像库
│   ├── protagonist.md         # 主人公画像
│   ├── family/                # 家庭成员
│   │   ├── father.md
│   │   ├── mother.md
│   │   └── ...
│   ├── friends/               # 朋友
│   └── colleagues/            # 同事
│
├── timeline/                  # 时间线库
│   ├── life-events.md         # 人生大事年表
│   └── detailed-timeline.md   # 详细时间线
│
├── themes/                    # 主题记忆库
│   ├── values.md              # 价值观形成
│   ├── turning-points.md      # 人生转折点
│   └── reflections.md         # 人生感悟
│
└── index.md                   # 总索引文件
```

### 3.3 Markdown 文件格式规范

#### 事件文件示例 (`events/childhood/birth-family.md`)

```markdown
# 出生家庭

## 基本信息
- **时间**：1950年
- **地点**：山东省青岛市
- **事件类型**：出生/家庭背景

## 事件描述
我出生在青岛一个普通工人家庭。父亲在纺织厂工作，母亲是家庭主妇。家里有五个孩子，我排行老三。

## 相关人物
- [[../people/father.md|父亲]]：张大明，纺织厂工人，性格严厉
- [[../people/mother.md|母亲]]：李秀英，家庭主妇，温柔善良

## 时间线关联
- [[../timeline/life-events.md#1950|人生大事年表 - 1950年]]

## 关键细节
- 家里住的是厂里分配的筒子楼
- 父亲每天骑自行车上班，往返20公里
- 母亲一个人拉扯五个孩子

## 情感标签
- #平淡 #温馨 #艰辛

## 来源
- 对话记录：session_001, turn_3-5
- 确认状态：已确认 ✓

## 待补充
- [ ] 父亲工作的纺织厂具体名称
- [ ] 童年时期家庭经济状况细节
```

#### 人物画像文件示例 (`people/family/father.md`)

```markdown
# 父亲 - 张大明

## 基本信息
- **关系**：父亲
- **姓名**：张大明
- **出生年份**：约1920年
- **职业**：纺织厂工人
- **性格特征**：严厉、沉默、勤劳

## 外貌特征
身材高大，方脸，总是穿着蓝色工作服。

## 性格特点
父亲话不多，很少表扬我们。但每天早起给我们热早饭，从不停歇。他用行动表达爱。

## 对主人公的影响
父亲的勤劳和沉默塑造了我对男人的认知——话少活多才是真本事。

## 关联事件
- [[../events/childhood/birth-family.md|出生家庭]]
- [[../events/youth/father-advice.md|父亲的教诲]]

## 重要语录
> "做人要踏实，别想那些没用的。"

## 关系图谱
```
父亲 ──┬── 我 (严厉但关爱)
       ├── 大哥
       ├── 二姐
       ├── 四弟
       └── 五妹
```

## 来源记录
- 对话记录：session_001, turn_3, 7, 12
- 确认状态：已确认 ✓
```

### 3.4 记忆检索机制

```python
async def query_memory(query_type, params):
    """
    多层记忆检索
    
    query_type:
    - "keyword": 关键词检索
    - "entity": 实体检索（人名/地名/时间）
    - "timeline": 时间线检索
    - "association": 关联发散检索
    """
    
    if query_type == "keyword":
        # 全文检索所有md文件
        results = await search_markdown_files(params["keyword"])
        return parse_and_rank(results)
    
    elif query_type == "entity":
        # 实体检索，优先画像记忆
        profile_result = await query_profile_memory(params["entity"])
        event_result = await query_event_memory(params["entity"])
        return merge_results(profile_result, event_result)
    
    elif query_type == "timeline":
        # 时间线检索
        return await query_timeline(params["start"], params["end"])
    
    elif query_type == "association":
        # 关联发散检索 - 供大模型联想
        return await follow_links(params["source_file"])
```

---

## 四、采访策略设计

### 4.1 采访启动策略

采访的开始至关重要，系统支持**多种启动策略**，Agent根据用户特征动态选择：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         采访启动策略选择                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   输入：用户初始状态（是否有准备、性格特征、时间充裕度）                    │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                      策略选择决策树                              │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│              ┌───────────────┼───────────────┐                         │
│              │               │               │                         │
│              ▼               ▼               ▼                         │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│   │ 策略A: 闪光点 │  │ 策略B: 时间线 │  │ 策略C: 主题式 │                │
│   │ 优先策略    │  │ 经典策略    │  │ 发散策略    │                │
│   └──────────────┘  └──────────────┘  └──────────────┘                │
│         │                  │                  │                        │
│         ▼                  ▼                  ▼                        │
│   "您人生中印象    "我们先从您出    "我们来聊聊您                      │
│   最深刻的一件事    生的地方开始    的成长经历，您                      │
│   是什么？"        好吗？"         最想分享的是                       │
│                                      哪个阶段？"                       │
│                                                                         │
│   适用：            适用：            适用：                           │
│   - 用户有准备      - 用户愿意按     - 用户不愿从头                    │
│   - 健谈型         部就班          - 有明确想说的                     │
│   - 时间有限       - 系统性强       主题                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 策略A：闪光点优先策略

**适用场景**：用户有准备、健谈、时间有限

**流程**：

```
启动 ──→ "您人生中印象最深刻的一件事是什么？"
           │
           ├── 用户讲述一个事件
           │      │
           │      ├── 追问细节：时间、地点、人物
           │      ├── 追问感受：当时怎么想？现在怎么看？
           │      └── 扩展关联：这件事前后发生了什么？
           │
           └── 从闪光点向前后延伸
                  │
                  ├── "这件事之前，您的生活是什么样的？"
                  └── "这件事之后，您的生活有什么变化？"
                          │
                          └── 继续挖掘其他闪光点，逐步覆盖完整时间线
```

**问题设计示例**：

| 阶段 | 问题类型 | 示例问题 |
|------|----------|----------|
| 开场 | 开放性 | "您人生中印象最深刻的一件事是什么？" |
| 追问细节 | 情景化 | "当时那个场景，您还记得吗？有哪些细节？" |
| 追问感受 | 情感性 | "那时候您是什么感受？现在回头看呢？" |
| 时间扩展 | 对比式 | "这件事前后，您的生活有什么变化？" |
| 深挖 | 假设式 | "如果重来一次，您会做不同的选择吗？" |

### 4.3 策略B：时间线经典策略

**适用场景**：用户愿意按部就班、系统性强

**流程**：

```
启动 ──→ "我们先从您出生的地方开始好吗？"
           │
           └── 按时间线顺序推进
                   │
       ┌───────────┼───────────┬───────────┬───────────┐
       ▼           ▼           ▼           ▼           ▼
    童年期      少年期      青年期      中年期      老年期
   (0-12岁)   (13-18岁)   (19-35岁)   (36-60岁)   (60岁+)
       │           │           │           │           │
       └───────────┴───────────┴───────────┴───────────┘
                           │
                   每个阶段覆盖：
                   - 关键事件
                   - 重要人物
                   - 心态变化
                   - 时代背景
```

**阶段问题库**：

```markdown
## 童年期 (0-12岁)

### 开场问题
- "您出生的地方是什么样的？"
- "您最早的记忆是什么？"

### 深入问题
- "小时候家里有几个兄弟姐妹？关系怎么样？"
- "童年最快乐的记忆是什么？"
- "童年最害怕什么？"
- "有没有哪位老师或长辈对您影响特别大？"
- "那时候家里的经济条件怎么样？"

### 追问技巧
- 细节追问："您说家里穷，能具体说说吗？比如吃饭、穿衣？"
- 情感追问："那时候您怎么想？现在怎么看？"
- 人物追问："您提到的那位老师，能多说说吗？"

## 少年期 (13-18岁)
[类似结构...]

## 青年期 (19-35岁)
[类似结构...]

## 中年期 (36-60岁)
[类似结构...]

## 老年期 (60岁+)
[类似结构...]
```

### 4.4 策略C：主题式发散策略

**适用场景**：用户不愿从头、有明确想说的主题

**流程**：

```
启动 ──→ "我们来聊聊您的成长经历，您最想分享的是哪个阶段？"
           │
           └── 用户选择主题
                   │
                   ├── "工作经历" ──→ 深挖职业发展
                   ├── "家庭故事" ──→ 深挖家庭关系
                   ├── "求学时光" ──→ 深挖学习经历
                   └── "其他主题" ──→ 灵活引导
                          │
                          └── 从主题向其他阶段辐射
                                  │
                                  └── 最终覆盖完整时间线
```

### 4.5 策略切换机制

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          策略动态切换机制                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   触发条件                          切换方向                            │
│   ─────────────────────────────────────────────────────────────────     │
│   用户回答"不知道从何说起"         策略A → 策略B（时间线引导）           │
│   用户主动提到闪光事件             任意策略 → 策略A（闪光点优先）        │
│   用户反复跑题                     任意策略 → 策略B（时间线约束）        │
│   用户情绪低落                     任意策略 → 暂停/情感陪伴模式          │
│   当前策略无进展超过3轮            切换到备选策略                        │
│                                                                         │
│   切换时的衔接话术：                                                     │
│   ─────────────────────────────────────────────────────────────────     │
│   "您刚才提到的那段经历很有意思，我们再聊聊那时候的事情好吗？"            │
│   "让我们换个方式，我先问几个简单的问题..."                             │
│   "看来这段回忆对您很重要，您慢慢说，我在听。"                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 五、对话状态管理

### 5.1 状态机设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        对话状态机                                        │
└─────────────────────────────────────────────────────────────────────────┘

    ┌──────────┐
    │  INIT    │ 初始化：加载用户画像，选择采访策略
    └────┬─────┘
         │
         ▼
    ┌──────────┐
    │ WARMUP   │ 破冰阶段：建立信任，轻松开场
    └────┬─────┘
         │
         ▼
    ┌──────────┐
    │ COLLECT  │ 采集阶段：按策略收集人生故事
    └────┬─────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌────────┐
│ DEEPEN │ │ REDIRECT│ 深挖模式    │ 重定向模式（跑题时）
└────┬───┘ └────┬────┘
     │          │
     └────┬─────┘
          │
          ▼
    ┌──────────┐
    │ PAUSE    │ 暂停阶段：用户疲劳/情绪波动/会话结束
    └────┬─────┘
         │
         ▼
    ┌──────────┐
    │ HANDOFF  │ 交接阶段：归纳内容，传递给下游Agent
    └──────────┘
```

### 5.2 状态转换触发条件

| 当前状态 | 触发条件 | 目标状态 | 说明 |
|----------|----------|----------|------|
| INIT | 用户首次发言 | WARMUP | 进入破冰阶段 |
| WARMUP | 破冰完成（用户放松） | COLLECT | 开始正式采集 |
| COLLECT | 用户提到重要事件 | DEEPEN | 深挖该事件 |
| COLLECT | 用户跑题超过2轮 | REDIRECT | 引导回到主线 |
| DEEPEN | 该话题挖掘完成 | COLLECT | 继续主线采集 |
| REDIRECT | 引导成功 | COLLECT | 恢复主线采集 |
| 任意 | 用户疲劳/时间到/情绪波动 | PAUSE | 暂停采集 |
| PAUSE | 会话结束或内容足够 | HANDOFF | 传递给下游 |

### 5.3 状态数据结构

```json
{
  "session_id": "session_20260419_001",
  "current_state": "COLLECT",
  "strategy": "sparkle_first",
  
  "turn_count": 15,
  "current_phase": "youth",  // 当前人生阶段
  
  "coverage": {
    "childhood": 0.8,   // 童年覆盖率
    "youth": 0.3,       // 少年覆盖率
    "young_adult": 0.0,
    "middle_age": 0.0,
    "elderly": 0.0
  },
  
  "current_topic": {
    "type": "event",
    "name": "第一份工作",
    "start_turn": 12,
    "depth": 2  // 挖掘深度
  },
  
  "emotion_state": {
    "type": "neutral",
    "intensity": "low",
    "last_change_turn": 10
  },
  
  "pending_questions": [
    "第一份工作的具体内容",
    "第一份工作的收入情况",
    "第一份工作对人生的影响"
  ],
  
  "collected_events": ["E001", "E002", "E003"],
  "collected_people": ["P001", "P002"],
  
  "last_activity": "2026-04-19T14:30:00Z"
}
```

---

## 六、措辞与情绪照顾

### 6.1 情绪识别与响应

```python
# 情绪识别维度
emotion_dimensions = {
    "valence": ["positive", "neutral", "negative"],  # 情感极性
    "intensity": ["low", "medium", "high"],          # 强度
    "type": [                                         # 具体类型
        "joy", "pride", "nostalgia",                # 正向
        "neutral", "curious",                       # 中性
        "sadness", "regret", "anger", "fear",       # 负向
        "confusion", "fatigue"                      # 特殊状态
    ]
}

# 响应策略矩阵
response_strategies = {
    ("sadness", "high"): {
        "action": "pause_and_comfort",
        "response": "我理解这段回忆对您来说有些沉重，我们可以先停一停，您想喝点水吗？",
        "next_action": "wait_for_user_signal"
    },
    ("regret", "medium"): {
        "action": "acknowledge_and_redirect",
        "response": "每个人的人生都有遗憾，但正是这些经历塑造了现在的您。您觉得这件事对后来有什么影响吗？",
        "next_action": "guide_to_positive"
    },
    ("joy", "high"): {
        "action": "encourage_elaboration",
        "response": "听起来那是一段非常美好的时光！能再多说说吗？当时的场景是什么样的？",
        "next_action": "deepen"
    },
    ("fatigue", "medium"): {
        "action": "suggest_pause",
        "response": "我们聊了不少了，您要不要休息一下？今天的内容我已经记下来了，下次继续。",
        "next_action": "save_and_pause"
    }
}
```

### 6.2 措辞得体指南

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          措辞得体指南                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  【原则1：尊重老人主体性】                                               │
│  ────────────────────────────────────────────────────────────────────  │
│  ❌ 避免："您应该..."、"您需要..."、"您最好..."                          │
│  ✅ 使用："您觉得..."、"您愿意聊聊..."、"如果您方便的话..."               │
│                                                                         │
│  【原则2：避免审问式提问】                                               │
│  ────────────────────────────────────────────────────────────────────  │
│  ❌ 避免：连续三个以上问题、打断老人发言                                  │
│  ✅ 使用：一次一个问题、耐心等待、适时回应                                │
│                                                                         │
│  【原则3：情感共鸣而非说教】                                             │
│  ────────────────────────────────────────────────────────────────────  │
│  ❌ 避免："您应该看开点"、"这没什么大不了的"                             │
│  ✅ 使用："我理解您的感受"、"那段日子确实不容易"                         │
│                                                                         │
│  【原则4：承认不知道，不硬问】                                           │
│  ────────────────────────────────────────────────────────────────────  │
│  ❌ 避免：反复追问老人记不清的内容                                        │
│  ✅ 使用："没关系，记得什么说什么"、"我们先聊聊别的"                     │
│                                                                         │
│  【原则5：年龄敏感话题处理】                                             │
│  ────────────────────────────────────────────────────────────────────  │
│  ❌ 避免：直接问"您今年多大"（显得唐突）                                 │
│  ✅ 使用：通过时间线推断，或问"您是哪一年出生的/哪一年参加工作的"         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.3 特殊场景话术模板

| 场景 | 推荐话术 |
|------|----------|
| **老人记不清** | "没关系，这是很正常的。我们先聊聊别的，说不定回头就想起来了。" |
| **老人情绪激动** | "我理解，这段回忆对您来说很重要。您慢慢说，我在听。" |
| **老人不愿多说** | "这个话题如果让您不舒服，我们换一个。您想聊聊别的吗？" |
| **老人跑题** | "您刚才说的很有意思。对了，您提到了XX，能多说说吗？" |
| **老人沉默很久** | "您在想什么呢？如果您愿意，可以说给我听听。" |
| **老人自责/后悔** | "每个人的人生都有不完美的地方。您觉得那件事对后来有什么影响吗？" |

---

## 七、内容归纳与传递机制

### 7.1 归纳触发机制

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        归纳触发机制                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   触发条件：                                                             │
│   ─────────────────────────────────────────────────────────────────     │
│   1. 实时触发：每轮对话结束后（异步，不阻塞）                             │
│   2. 阶段触发：完成一个人生阶段采集后                                     │
│   3. 事件触发：检测到完整事件描述后                                       │
│   4. 会话触发：会话暂停/结束时                                           │
│                                                                         │
│   触发流程：                                                             │
│   ─────────────────────────────────────────────────────────────────     │
│                                                                         │
│   对话轮次 ──→ 检测触发条件 ──→ 执行归纳任务                              │
│                                    │                                    │
│                                    ├── 更新短期记忆                      │
│                                    ├── 更新长期记忆（md文件）            │
│                                    ├── 更新画像记忆                      │
│                                    └── 检查是否需要传递下游              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 归纳内容标准格式

```json
{
  "summary_id": "sum_20260419_001_015",
  "session_id": "session_20260419_001",
  "turn_range": [12, 15],
  "created_at": "2026-04-19T14:30:00Z",
  
  "extracted_info": {
    "events": [
      {
        "event_id": "E004",
        "title": "第一份工作",
        "time": "1970年",
        "time_precision": "year",
        "location": "青岛纺织厂",
        "type": "career",
        "description": "经父亲介绍进入纺织厂工作，从学徒工做起",
        "details": [
          "每月工资18元",
          "工作三班倒",
          "师傅叫王大爷"
        ],
        "participants": ["我", "父亲", "王大爷(师傅)"],
        "emotions": ["紧张", "自豪"],
        "significance": "人生第一份工作，开始独立生活"
      }
    ],
    
    "people": [
      {
        "person_id": "P003",
        "name": "王大爷",
        "role": "师傅",
        "description": "纺织厂老工人，教我技术",
        "relation_to_protagonist": "职场引路人",
        "source_events": ["E004"]
      }
    ],
    
    "time_markers": [
      {
        "time": "1970年",
        "events": ["E004"],
        "phase": "youth"
      }
    ],
    
    "themes": [
      {
        "theme": "独立",
        "related_events": ["E004"],
        "description": "开始工作，经济独立"
      }
    ]
  },
  
  "memory_updates": {
    "short_term": {
      "current_topic": "第一份工作",
      "mentioned_people": ["父亲", "王大爷"],
      "mentioned_times": ["1970年"],
      "mentioned_places": ["纺织厂"]
    },
    
    "long_term": {
      "files_to_update": [
        "events/youth/first-job.md",
        "people/colleagues/wang-daye.md",
        "timeline/life-events.md"
      ]
    },
    
    "profile": {
      "career_start": "1970年",
      "first_employer": "青岛纺织厂",
      "first_job": "学徒工"
    }
  },
  
  "pending_questions": [
    "在纺织厂工作了多久？",
    "后来为什么离开纺织厂？"
  ],
  
  "handoff_ready": false,
  "handoff_reason": null
}
```

### 7.3 传递给下游Agent的触发条件

```python
def should_handoff_to_agent_b(state):
    """
    判断是否应该将归纳内容传递给结构化内容整理层(Agent-B)
    """
    
    conditions = [
        # 条件1：完成一个人生阶段的采集
        state["current_phase_complete"] == True,
        
        # 条件2：会话暂停/结束
        state["current_state"] == "PAUSE" and state["pause_type"] == "session_end",
        
        # 条件3：收集到足够多的事件
        len(state["collected_events"]) >= 10,
        
        # 条件4：用户主动要求整理
        state["user_requested_summary"] == True,
        
        # 条件5：时间间隔触发（如每30分钟）
        time_since_last_handoff() > 30 * 60
    ]
    
    return any(conditions)
```

### 7.4 Handoff 内容结构

```json
{
  "handoff_id": "handoff_20260419_001",
  "from_agent": "Agent-A",
  "to_agent": "Agent-B",
  "timestamp": "2026-04-19T15:00:00Z",
  
  "session_info": {
    "session_id": "session_20260419_001",
    "total_turns": 25,
    "duration_minutes": 45,
    "strategy_used": "sparkle_first"
  },
  
  "collection_progress": {
    "childhood": {"coverage": 0.8, "events": 3, "people": 4},
    "youth": {"coverage": 0.5, "events": 2, "people": 2},
    "young_adult": {"coverage": 0.0, "events": 0, "people": 0},
    "middle_age": {"coverage": 0.0, "events": 0, "people": 0},
    "elderly": {"coverage": 0.0, "events": 0, "people": 0},
    "overall_coverage": 0.26
  },
  
  "collected_data": {
    "events": [...],   // 事件列表
    "people": [...],   // 人物列表
    "timeline": [...], // 时间标记
    "themes": [...]    // 主题
  },
  
  "raw_conversations": {
    "file_path": "conversations/session_20260419_001.md",
    "format": "markdown"
  },
  
  "pending_questions": [...],
  
  "notes_for_agent_b": [
    "用户童年记忆较为模糊，需耐心追问",
    "用户对父亲有复杂情感，需敏感处理",
    "用户对第一份工作记忆清晰，可深入挖掘"
  ]
}
```

---

## 八、完整流程示例

### 8.1 一次完整对话流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    完整对话流程示例                                      │
└─────────────────────────────────────────────────────────────────────────┘

【INIT阶段】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
系统：加载用户画像... 用户首次使用，选择策略A（闪光点优先）
系统：初始化记忆库... 创建空的md文件结构

【WARMUP阶段】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Turn 1:
Agent: "您好！很高兴能听您讲述您的故事。在开始之前，您有什么特别想和我分享的吗？或者我们可以随便聊聊？"
[异步] 情绪识别：neutral, low
[异步] 知识库查询：无相关记忆
[异步] 内容归纳：无需归纳

用户: "我今年75岁了，一辈子在青岛，也没去过别的地方。"

Turn 2:
Agent: "青岛是个好地方，您一辈子都在这里，一定有很多故事吧？您人生中有没有哪件事让您印象特别深刻？"
[异步] 情绪识别：neutral, low
[异步] 知识库查询：无相关记忆
[异步] 内容归纳：
  - 人物画像更新：年龄75岁，地点青岛
  - 状态：WARMUP → COLLECT

【COLLECT阶段 - 策略A】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Turn 3:
用户: "印象最深...应该是1978年我女儿出生那年，那时候日子苦，但是高兴。"

Agent: "1978年，女儿出生，这确实是人生大事。能说说那时候的情况吗？比如您当时在做什么工作？"
[异步] 情绪识别：joy, medium
[异步] 知识库查询：timeline/1978
[异步] 内容归纳：
  - 事件 E001：1978年女儿出生
  - 时间标记：1978年 → middle_age阶段
  - 人物 P001：女儿

Turn 4:
用户: "那时候我在纺织厂上班，三班倒，挣得不多。她妈生孩子时候我正在夜班，赶回来的时候孩子已经出生了。"

Agent: "您当时一定很着急想赶回去吧？能说说当时的具体情况吗？您是怎么知道消息的？"
[异步] 情绪识别：nostalgia, medium
[异步] 知识库查询：events/youth/first-job.md（纺织厂）
[异步] 内容归纳：
  - 事件 E001 补充：工作单位纺织厂，三班倒
  - 事件 E001 细节：夜班时孩子出生
  - 情感标签：焦急、遗憾、喜悦

Turn 5:
用户: "是邻居跑来厂里告诉我的。我骑着自行车就往医院跑，那时候路不好走，骑了半个多小时..."

Agent: "半个多小时的夜路，您心里一定很着急。到了医院看到孩子的时候是什么感觉？"
[异步] 情绪识别：joy, high
[异步] 内容归纳：
  - 事件 E001 细节：邻居通知、骑车半小时
  - 深挖模式触发 → DEEPEN

【DEEPEN阶段】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Turn 6-8:
[深入挖掘女儿出生事件]
- 医院场景
- 初见女儿的感受
- 当晚的经历
- 对未来的期望

[内容归纳完成，写入md文件]
events/middle-age/daughter-born.md 创建
people/family/daughter.md 创建

【回到COLLECT阶段】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Turn 9:
Agent: "您女儿出生那年是1978年，那时候您应该已经工作一段时间了。您是什么时候开始工作的？"
[从当前事件向前追溯]

用户: "我1970年进的纺织厂，那时候20岁。"

Agent: "20岁进纺织厂，那是您第一份工作吗？能说说您是怎么进厂的？"
[继续按时间线向前挖掘]

... [继续对话] ...

【PAUSE阶段】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Turn 25:
[检测到用户疲劳]
系统：用户沉默时间过长，情绪识别为fatigue

Agent: "我们今天聊了很多，您辛苦了。我先把今天的内容整理一下，下次我们继续。您看这样安排可以吗？"

用户: "好，有点累了。"

【HANDOFF阶段】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
系统：触发归纳Agent批量处理
系统：更新所有md文件
系统：生成Handoff工件 → Agent-B

Handoff内容摘要：
- 对话轮数：25轮
- 采集阶段：童年(80%)、青年(60%)、中年(30%)
- 收集事件：8个
- 收集人物：6个
- 原始对话：conversations/session_20260419_001.md
```

---

## 九、技术实现要点

### 9.1 异步任务调度

```python
import asyncio
from typing import Optional

class ConversationOrchestrator:
    """
    对话主控Agent - 协调所有异步任务
    """
    
    def __init__(self):
        self.emotion_agent = EmotionAgent()
        self.memory_agent = MemoryAgent()
        self.question_agent = QuestionAgent()
        self.summary_agent = SummaryAgent()
        
    async def process_turn(self, user_input: str, state: dict) -> str:
        """
        处理一轮对话
        """
        # 并行启动异步任务
        emotion_task = asyncio.create_task(
            self.emotion_agent.detect(user_input, state["conversation_history"])
        )
        memory_task = asyncio.create_task(
            self.memory_agent.query(user_input, state)
        )
        summary_task = asyncio.create_task(
            self.summary_agent.summarize_async(user_input, state["turn_count"])
        )
        
        # 等待关键任务完成（有超时保护）
        try:
            emotion_result = await asyncio.wait_for(emotion_task, timeout=3.0)
        except asyncio.TimeoutError:
            emotion_result = EmotionResult.neutral()
        
        try:
            memory_result = await asyncio.wait_for(memory_task, timeout=5.0)
        except asyncio.TimeoutError:
            memory_result = MemoryResult.empty()
        
        # 内容归纳延迟执行，不等待
        # summary_task 会在后台完成
        
        # 生成下一个问题
        next_question = await self.question_agent.generate(
            user_input=user_input,
            emotion=emotion_result,
            memory=memory_result,
            state=state
        )
        
        # 更新状态
        state = self.update_state(state, user_input, emotion_result)
        
        return next_question
```

### 9.2 记忆库文件操作

```python
import os
from pathlib import Path
from datetime import datetime

class MemoryFileManager:
    """
    记忆库文件管理器
    """
    
    def __init__(self, base_path: str = "memory"):
        self.base_path = Path(base_path)
        
    async def create_event_file(self, event: dict) -> str:
        """
        创建事件md文件
        """
        # 确定目录
        phase = self._get_phase(event["time"])
        dir_path = self.base_path / "events" / phase
        
        # 生成文件名
        filename = self._generate_filename(event["title"])
        file_path = dir_path / f"{filename}.md"
        
        # 写入内容
        content = self._render_event_markdown(event)
        await self._write_file(file_path, content)
        
        return str(file_path)
    
    async def update_timeline(self, event: dict):
        """
        更新时间线文件
        """
        timeline_path = self.base_path / "timeline" / "life-events.md"
        await self._append_to_timeline(timeline_path, event)
    
    async def query_by_keyword(self, keyword: str) -> list:
        """
        全文检索关键词
        """
        results = []
        for md_file in self.base_path.rglob("*.md"):
            content = await self._read_file(md_file)
            if keyword.lower() in content.lower():
                results.append({
                    "file": str(md_file),
                    "relevance": self._calculate_relevance(content, keyword)
                })
        return sorted(results, key=lambda x: x["relevance"], reverse=True)
    
    def follow_links(self, file_path: str) -> list:
        """
        追踪md文件中的链接，获取关联内容
        """
        content = self._read_file(file_path)
        links = self._extract_wikilinks(content)
        related = []
        for link in links:
            linked_content = self._read_file(link)
            related.append({
                "source": link,
                "content": linked_content[:500]  # 预览前500字
            })
        return related
```

### 9.3 问题生成Agent

```python
class QuestionGenerator:
    """
    问题生成Agent - 根据状态和记忆生成下一个问题
    """
    
    def __init__(self, question_templates: dict):
        self.templates = question_templates
        
    async def generate(
        self,
        user_input: str,
        emotion: EmotionResult,
        memory: MemoryResult,
        state: dict
    ) -> str:
        """
        生成下一个问题
        """
        # 1. 检查是否需要情绪响应
        if emotion.needs_special_handling():
            return self._generate_emotion_response(emotion, user_input)
        
        # 2. 检查是否有待追问的问题
        if state.get("pending_questions"):
            return self._generate_follow_up(state["pending_questions"].pop(0), memory)
        
        # 3. 检查是否需要切换阶段
        if self._should_change_phase(state):
            return self._generate_phase_transition(state)
        
        # 4. 基于记忆和状态生成新问题
        return self._generate_contextual_question(state, memory)
    
    def _generate_emotion_response(self, emotion, user_input) -> str:
        """
        根据情绪状态生成响应
        """
        if emotion.type == "sadness" and emotion.intensity == "high":
            return "我理解这段回忆对您来说有些沉重。我们可以换个话题，或者您想先休息一下？"
        elif emotion.type == "fatigue":
            return "我们今天聊了很多，您要不要休息一下？内容我已经记下了。"
        # ... 其他情绪处理
    
    def _generate_contextual_question(self, state, memory) -> str:
        """
        基于上下文生成问题
        """
        current_phase = state["current_phase"]
        strategy = state["strategy"]
        coverage = state["coverage"][current_phase]
        
        if coverage < 0.3:
            # 覆盖率低，用开放性问题
            return self._get_open_question(current_phase)
        elif coverage < 0.7:
            # 覆盖率中等，用追问性问题
            return self._get_follow_up_question(state, memory)
        else:
            # 覆盖率高，准备切换阶段
            return self._get_phase_summary_question(current_phase)
```

---

## 十、附录

### A. 事件类型分类

| 类型 | 说明 | 示例 |
|------|------|------|
| birth | 出生/家庭背景 | 出生地、家庭情况 |
| education | 求学经历 | 上学、升学 |
| career | 工作经历 | 就业、换工作、退休 |
| marriage | 婚姻家庭 | 结婚、生子 |
| relocation | 迁移搬迁 | 搬家、下乡、回城 |
| achievement | 成就时刻 | 获奖、晋升 |
| challenge | 困难挑战 | 疾病、失业、亲人离世 |
| travel | 旅行经历 | 特殊旅行经历 |
| historical | 历史事件 | 亲历的重大历史事件 |

### B. 人物关系类型

| 关系类型 | 说明 |
|----------|------|
| immediate_family | 直系亲属（父母、子女） |
| extended_family | 扩展家庭（兄弟姐妹、亲戚） |
| spouse | 配偶 |
| friend | 朋友 |
| colleague | 同事 |
| mentor | 导师/引路人 |
| classmate | 同学 |
| neighbor | 邻居 |

### C. 情绪标签体系

```
正向情绪：
- joy (喜悦)
- pride (自豪)
- nostalgia (怀念)
- gratitude (感恩)
- hope (希望)

中性情绪：
- neutral (平静)
- curious (好奇)
- contemplative (沉思)

负向情绪：
- sadness (悲伤)
- regret (后悔)
- anger (愤怒)
- fear (恐惧)
- guilt (愧疚)

特殊状态：
- confusion (困惑)
- fatigue (疲劳)
- reluctance (抗拒)
```

---

## 十一、设计总结

### 核心设计要点

1. **异步流水线**：问题生成、知识库查询、内容归纳三者异步并行，提高响应速度
2. **三层记忆**：短期记忆保对话连贯，长期记忆持久化知识，画像记忆供发散联想
3. **文件系统知识库**：md格式存储，内部链接互联，便于检索和追溯
4. **多策略采访**：闪光点优先、时间线经典、主题式发散三种策略灵活切换
5. **情绪感知**：实时识别情绪状态，动态调整对话策略
6. **标准化归纳**：统一的JSON格式，明确的触发机制，平滑传递给下游

### 与其他Agent的协作

```
问答引导层 (Agent-A)
    │
    │ 输出：结构化归纳内容 + 原始对话记录
    │
    ▼
结构化内容整理层 (Agent-B)
    │ 进一步抽取、整理、建立关联
    │
    ▼
时间线梳理层 (Agent-C)
    │ 组织时间线，生成创作大纲
    │
    ▼
撰写层 (Agent-D)
    │ 基于记忆库和写作prompt生成文稿
    │
    ▼
输出：自传草稿
```

---

**文档完成**，可作为开发实现的技术规范。

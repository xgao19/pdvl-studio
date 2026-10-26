# Discuss 真实论文质量基线 · 2026-10-26

本轮冻结三个 arXiv 版本、20个研究问题，使用现有 Ollama `deepseek-v4.1-flash:1017` 完成一次逐题运行。经原文代理审阅：13题支撑充分、7题需改进；这不是独立领域专家认证或稳定的模型准确率。Discuss 行为、提示词、检索排序和默认 API 配置均未为了本轮结果调优。

来源为 [2206.01105v1](https://arxiv.org/abs/2206.01105v1)、[2003.06063v2](https://arxiv.org/abs/2003.06063v2)、[2103.16991v3](https://arxiv.org/abs/2103.16991v3)，共50个 PDF 页。版本、PDF与分页文本哈希、20题及其参考页/短锚点/判据见 [评测集](../../evals/discuss_real_papers.json)；机器可读的结果与逐题审阅见 [结果快照](discuss-baseline-2026-10-26.json)。PDF和完整模型轨迹只保存在忽略的本地评测目录。

| 维度 | 本轮结果 | 含义 |
|---|---:|---|
| 执行完成 | 20/20 | 一次运行，不含重复采样 |
| 原问题检索 Hit@8 | 14/20，70% | 不做问题翻译或人工关键词改写，至少一个标注页进入前8 |
| 原问题标注页 Recall@8 | 57.7% | 每题平均；不是所有真正相关页的穷尽召回率 |
| 模型调用项目搜索 | 14/20 | 其余题直接按文献身份读页，不能算搜索失败 |
| 已调用搜索题的标注页覆盖 | 85.7% | 多次工具查询结果的并集，不等同单查询 Recall@8 |
| 实际阅读标注页覆盖 | 88% | 页访问指标；不自动证明读过整页或正确理解 |
| 归档引用访问校验 | 73/74 | 只校验身份、页码及读取；18/20题给出可点击引用 |
| 原文代理审阅 | 13通过，7需改进 | 核查请求要点、额外论断及具体页的支撑；非关键词评分 |
| 关键限制代理审阅 | 20/20有提及 | 问题多主动询问限制，不代表自发发现能力或无遗漏保证 |

## 主要发现

- **阅读质量比单纯增加搜索更紧迫。** Q01把表格的快度范围读错；Q18把表格粘连数字误读成516 GeV。二者的来源链接可以完全有效，原文理解仍会出错。
- **引用存在不等于逐断言有依据。** Q04的多页标签只指向一页；Q12的一处未读页链接被拦截；Q09、Q15只有裸页码，没有可点击引用。Q19主结论虽正确，额外的核提取公式却漏了匹配项。
- **过度解释也会引入错误。** Q06混淆了约1%估计的来由；Q09对高阶匹配的说法过度简化；Q14把同一归一化方法的理论描述和数值实现写得像两条独立路线。
- **金标准页并非唯一正确页。** Q13没有读预标注引言页，但在相邻方法页找到了等价支持。零标注页覆盖不能自动判语义失败；需继续校准相关页标签。

## 评测边界与审阅说明

每题从同一个公开文献库、空对话状态开始，不携带之前问题、答案、人工标签或参考结论。运行通过现有 `/chat` API和工具执行；无外部文献搜索、无新的模型服务、无证据登记。答案生成与评分材料分开：代码检查版本/哈希、检索、实际读取和引用访问；原文支撑和限制由 Codex 对照原文与读取轨迹逐项审阅，`independent_expert_review=false`。默认不会让同一回答模型给自己打正确性分，也不会把没有审阅的结果记为通过。审阅检查额外论断，不因核心答案正确就忽略附加错误；轻微或有歧义之处标为需改进，仍待领域专家校准。

发布前标签审阅修正了 Q19：该题只问两篇文献，初始限制判据误挂了无关第三篇的页锚点，现已删除。问题、模型输入、原始回答完全不变，只重算确定性的访问指标；原始版本在本地保留，修正理由记录在结果manifest中。这是标签纠正，不是运行后调整检索或提示词。

这些20题主要来自 CS-kernel 主题，含少量中英对照、数值、方法限制、跨论文比较和不可回答题。它们适合作为开发诊断集；样本小、仅一次运行、问题较有引导性，没有独立专家标注或隐藏测试集，不能外推到全部物理文献。数据导入也可能因远程内容变化而失败；哈希不一致会显式停止，不会静默更新版本。

## 下一步建议

1. 先用本轮失败题改进表格/公式的原页对照、抽取风险标记和逐断言出处核对，重点回归数字范围、遗漏项与页码对应。
2. 补一组不主动提醒“注意局限”的隐藏问题，并由领域专家校准这批代理判据，避免只在这20题上反复调优。更新标签应单独版本化，保留前后结果。
3. 再比较“原问题关键词检索”与“术语/中英文查询改写”；只有在独立问题上能带来收益，再考虑 embeddings 或重排器。优先维持现有轻量技术栈。

这遵循把检索过程与回答支撑/完整性分开评估的做法（[Microsoft RAG evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators)），也采用保留完整轨迹、校准评分器并审查评测任务本身的原则（[Anthropic agent evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)）。本轮没有添加依赖，没有发布安装包或 Release。

下面保留逐题诊断和审阅理由。

## 逐题记录

One trial per question; same configured Discuss API and tools; cold conversation; no gold labels in model input.

Model: deepseek-v4.1-flash:1017; questions: 20; completed: 20.
Raw question hit@8: 70.0%; mean labeled-page recall@8: 57.7%.
Tool-search union page recall: 60.0%; actual read-page recall: 88.0%.
Tool search used in 14/20 cases; direct reading is allowed and is not a search failure.
Citation access checks: 73/74; answers with clickable citations: 18/20.
Support: {'needs_work': 7, 'pass': 13}; key limitations: {'pass': 20}.

Source access is not semantic support. Anchors only measure exposure, not entailment. Missing reviews are unreviewed, never passes.
Gold pages are non-exhaustive labels: equivalent support on other original pages is adjudicated in the source audit. Extra unsupported claims downgrade support even when the requested core fact is correct.
The same model is not used to certify its own answers. Source audit is not independent physics validation.

| Case | State | Raw labeled-page recall@8 | Read labeled-page recall | Support | Limitations |
|---|---|---:|---:|---|---|
| Q01 | completed | 100% | 100% | needs work | pass |
| Q02 | completed | 100% | 100% | pass | pass |
| Q03 | completed | 100% | 100% | pass | pass |
| Q04 | completed | 100% | 100% | needs work | pass |
| Q05 | completed | 0% | 100% | pass | pass |
| Q06 | completed | 100% | 100% | needs work | pass |
| Q07 | completed | 100% | 100% | pass | pass |
| Q08 | completed | 100% | 100% | pass | pass |
| Q09 | completed | 100% | 100% | needs work | pass |
| Q10 | completed | 0% | 100% | pass | pass |
| Q11 | completed | 0% | 100% | pass | pass |
| Q12 | completed | 50% | 100% | pass | pass |
| Q13 | completed | 0% | 0% | pass | pass |
| Q14 | completed | 50% | 50% | needs work | pass |
| Q15 | completed | 0% | 100% | pass | pass |
| Q16 | completed | 33% | 100% | pass | pass |
| Q17 | completed | 100% | 100% | pass | pass |
| Q18 | completed | 20% | 60% | needs work | pass |
| Q19 | completed | 100% | 100% | needs work | pass |
| Q20 | completed | 0% | 50% | pass | pass |

## Q01: 2206.01105v1 的 CASCADE 方法演示使用什么数据和参数输入？这是否等于完成真实实验数据提取？
- facts/data: partial — 主干的 CASCADE 伪数据与 HERA 输入有原文支撑，但额外给出的 δy=2–6 与 PDF 第2页表 I 不符（应包含2、3、4、5，未有6）；p.1,p.4 标签只链接到p.1。不能因主干答对就忽略附加错误。
- limitations/scope: present — 正确区分方法演示与已完成真实数据提取；统计/系统误差措辞混淆列入支撑问题。

## Q02: In 2206.01105v1, what data and parameter inputs drive the CASCADE demonstration? Is it an extraction from real experimental data?
- facts/data: supported — 输入与伪数据性质可在已读 PDF 第2–4页核对；没有把既有 DY 描述能力误称为本文的实测输入。英文问题得到中文回答，不影响本次事实评分。
- limitations/scope: present — 明确本文未完成真实数据提取，实际数据应用属于后续工作。

## Q03: 2206.01105v1 中怎样选 s、Q、y 才能在截面比中消掉 TMD？积分分箱的 δQ 与 δy 有什么限制？
- facts/matching: supported — 同 y、同 b、s1/s2=Q1²/Q2² 及 x1,x2 相同均对应第1–2页方程与说明；分箱条件对应第2页。
- limitations/bins: present — 保留 δQ≪Q、两组 δy 相同以及因子化适用范围，未声称任意截面相消。

## Q04: 2206.01105v1 的离散 Hankel 变换为何不能无条件延伸到任意大 b？说明 qT 分箱、稳定区间与误差估计。
- facts/bins: partial — 分箱0.05 GeV、可达4–5 GeV⁻¹及 bootstrap 有支撑；但把图2的4–6区间振荡标为p.3–4却仅链接p.3，该图及对应caption实际在p.4。事实大体正确，逐断言页码对应尚不足。
- limitations/instability: present — 区分高 qT 截断很小与有限分箱仍不稳定，并指出大 b 的输入密度要求。

## Q05: 2206.01105v1 的大 b 线性渐近结果属于什么对象？能否据此断言真实 QCD 核的精确普适渐近形式？
- facts/asymptotic: supported — CASCADE 的线性拟合及范围限制与第3–4页一致；补充两篇格点结果的限定比较可在实际读取的页中核对。
- limitations/scope: present — 明确这是生成器模型所隐含行为的有限范围拟合，不是真实 QCD 精确渐近定理。

## Q06: 2206.01105v1 的 Drell–Yan 方法对 qT/Q、Q 与强作用尺度、Z 玻色子有什么适用条件？约 1% 修正对应哪里？
- facts/power: partial — 适用尺度和约1%的位置正确；最后把该估计归因为 CASCADE 演示不准确。第2页该处引用的是已有因子化分析，不能把论文中所有数值都归到伪数据实验。
- limitations/window: present — 保留 Q≫Λ、Q≪MZ、需纳入 Z 修正，以及1%并非严格误差上界的限定。

## Q07: 2003.06063v2 用什么海夸克设置、外态及 pion 质量？态无关性是否意味着所有有限动量误差也无关？
- facts/ensemble: supported — quenched、重 pion 质量和外态的说明对应第4页，有限动量及外态依赖的修正也有直接原文。
- limitations/state: present — 明确核的态无关不等于其幂修正态无关，也未称为含海夸克物理点结果。

## Q08: 2003.06063v2 的准 beam function 中，Dirac 结构混合贡献有多大？能否只算 γ4 就保证更高精度？
- facts/mixing: supported — 5%–25%和多个 Dirac 结构的精度要求均对应第6页；额外的统计设置可在第4页核对。
- limitations/precision: present — 将该幅度限定为所研究参数下的准 beam function 混合贡献，未当作通用最终核误差。

## Q09: Why does 2003.06063v2 model the longitudinal quasi beam function before Fourier transformation? Is its final kernel model independent?
- facts/truncation: partial — 截断、两类模型及非模型无关结论有支撑；“高阶匹配会破坏x无关性而被忽略”把原文需要更复杂拟合形式补偿x依赖的说明简化过度，易与物理核的x无关性混淆。另有裸页码而无可点击出处。
- limitations/dependence: present — 保留模型依赖及更大体积/更大 Pz*bzmax 的需要，没有称两模型一致就消除了系统误差。

## Q10: 2003.06063v2 的最终模型分析采用怎样的微扰匹配阶次？能否说已严格控制所有高阶匹配和幂修正？
- facts/order: supported — LO=1、忽略高阶匹配和未约束幂修正均可在已读第6、8–11页核对。
- limitations/uncertainty: present — 明确探索性而非完全受控；区分预期较小与已给出误差上限。

## Q11: 2003.06063v2 认为未来实现受控、模型无关 CS 核需要哪些改进？只增加统计量够吗？
- facts/improvements: supported — 更大体积、纵向范围和动量的建议及示例截断估计来自第10–11页；对独立极限的要求有原文支撑。
- limitations/limits: present — 明确只增加统计量不足，仍需连续极限、无限体积及幂修正控制。

## Q12: 2103.16991v3 的 H101 是 quenched 还是 dynamical？给出 Nf、格距与质量，并说明是否已外推到物理点。
- facts/ensemble: supported — H101 的动力学设置、格距、质量与单ensemble范围正确。额外引用 quenched 论文p.1未实际读取，已被系统拦截；此机械问题独立记录，不应把事实正确和访问校验混为一谈。
- limitations/physical: present — 明确非物理质量、单一格距/体积与尚未外推物理点。

## Q13: 2103.16991v3 为什么研究第一 Mellin 矩、只用 ℓ=0 比值？是否因此完全去掉了 x 依赖的模型假设？
- facts/moment: supported — 实际读取的是第4–9页及另一篇第10–11页，而非预标注引言p.3；ℓ=0、积分矩及 M/r 的模型假设在这些正文页有等价支持。标注页访问为0不能直接判语义错误。
- limitations/assumption: present — 明确 x 依赖被压缩进积分组合与常数假设，而非被消除。

## Q14: 2103.16991v3 怎样处理 M(b) 与归一化？由它得到的 δK 是否等于全部系统误差？
- facts/normalization: partial — 常数假设与关联系统误差基本正确，但把第2.3节的理论归一化与第4.1节在1.20/1.28处拟合 M 写成“另一条路线”，混淆同一方法的理论描述和数值实现。
- limitations/incomplete: present — 明确 δK 不是全部系统误差，列出未受控的格点伪影、有限 staple 及幂修正。

## Q15: 2103.16991v3 认为提取可靠的 b 范围是多少？为什么小 b 和大 b 两端不能直接信任？
- facts/range: supported — 可靠窗口与两端失效原因可在第17–20页核对；没有附可点击页码链接，单独记为引用呈现缺口，不自动判事实错误。
- limitations/ends: present — 将窗口限定为该ensemble、动量与方法，并保留常数假设及未完全控制的系统误差。

## Q16: 2103.16991v3 的 Sivers 情形为何不能直接沿用无偏振通道的稳定假设？哪些实际提取通道最终被排除？
- facts/sivers: supported — 非正定导致比值奇异与实际三个被排除通道均有正文支撑；实际排除的格点伪影解释也已读到。
- limitations/cause: present — 区分 Sivers 的积分风险与格点分析中的排除原因，未说所有通道均受控。

## Q17: 2103.16991v3 的约 30%–40% 幂修正估计来自什么比较？它是否就是最终 CS 核的总相对误差？
- facts/estimate: supported — bad/good 比值、对应动量、b值和约40%/30%的说明与第17页一致。把结论页口误称摘要页是位置称呼问题，实际链接页存在且已读。
- limitations/interpretation: present — 明确不是核的总相对误差，并保留比值部分相消、M拟合及其他系统误差。

## Q18: 比较 2206.01105v1、2003.06063v2 和 2103.16991v3：各自数据来源和主要方法障碍是什么？结果接近是否证明物理 QCD 普适性？
- facts/sources: partial — 三种数据来源主干正确，但把第2页表格粘连成 Q=12–516 GeV；原表相关 Q 为12、16、20、24 GeV，516不是质量点。原文链接有效未防住数值误读。
- limitations/comparison: present — 保留伪数据、quenched与动力学非物理质量的区别、建模/常数假设和受限 b 窗口，未宣称完成普适性证明。

## Q19: 对照 2206.01105v1 式(3) 与 2103.16991v3 式(2.12)：若使用同一个 ζ 导数，D 与 K 是否只差负号？叠图还需核对什么？
- facts/factor: partial — D=-K/2 的主要比较正确；但额外把式(2.24)写成 K=ln R/ln(P1/P2)，遗漏 ln r。真正的核提取并非这一简式，尤其同文正在讨论匹配项。
- limitations/alignment: present — 明确需核对原始方程、ζ和共同μ、有限b窗口与关联误差，没有直接只翻符号叠图。单位检查仍可更显式，后续用更细判据复核。

## Q20: 这三篇是否提供了同一物理点、连续极限下 CS 核在 b=5 GeV⁻¹ 的联合 95% 置信区间？若没有，说明缺口，不要编造数值。
- facts/abstain: supported — 恰当拒绝编造共同物理点连续极限的联合95%区间；使用的版本和已读材料不提供所要求的联合结果。预标注部分页未读，但实际读页提供了等价限制依据。
- limitations/gaps: present — 保留 quenched、非物理质量、伪数据、大b范围和缺少共同协方差等缺口。

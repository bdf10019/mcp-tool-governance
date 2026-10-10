import { useEffect, useMemo, useState } from "react";
import evidence from "./evidence-summary.json";
import './portfolio-guide.css';

type ProfileId = "service" | "asset";
type ToolId = "status" | "history" | "parts" | "order";
type RoleId = "viewer" | "operator" | "reviewer" | "admin";
type RestoreState = "idle" | "blocked" | "verified";

const chapters = [
  ["overview", "01", "作品總覽"],
  ["profiles", "02", "客戶模式"],
  ["tools", "03", "四個工具"],
  ["scope", "04", "權限範圍"],
  ["approval", "05", "人工核准"],
  ["idempotency", "06", "冪等寫入"],
  ["configuration", "07", "設定版本"],
  ["restore", "08", "備份還原"],
  ["trace", "09", "Trace 隔離"],
  ["evidence", "10", "證據限制"],
] as const;

const profiles = {
  service: {
    name: "維修服務商",
    short: "快速派修",
    description: "重視快速判讀、派修與交接，單人核准即可進入執行。",
    approvals: 1,
    retention: "1 日",
    fields: ["設備", "異常摘要", "優先序", "現場狀態"],
    scope: ["EQ-PUMP-001", "EQ-FAN-002", "EQ-CONV-003"],
    color: "青綠",
  },
  asset: {
    name: "廠內設備管理團隊",
    short: "風險治理",
    description: "重視資產風險、維護時段與來源證據，需要兩名不同 reviewer。",
    approvals: 2,
    retention: "7 日",
    fields: ["設備", "異常摘要", "優先序", "工況", "量測", "維護時段", "風險說明", "來源證據"],
    scope: ["EQ-PUMP-001", "EQ-CHILLER-004"],
    color: "訊號紫",
  },
} satisfies Record<ProfileId, {
  name: string;
  short: string;
  description: string;
  approvals: number;
  retention: string;
  fields: string[];
  scope: string[];
  color: string;
}>;

const tools: Array<{ id: ToolId; name: string; kind: "read" | "write"; description: string; output: string }> = [
  { id: "status", name: "設備狀態", kind: "read", description: "確認循環水泵目前是否降級。", output: "degraded｜資料版本 eq-seed-v3" },
  { id: "history", name: "維修紀錄", kind: "read", description: "查看軸承溫度與軸封維修歷史。", output: "2 筆｜軸承複查、軸封試運轉" },
  { id: "parts", name: "零件相容性", kind: "read", description: "查詢相容零件及合成庫存。", output: "6204 軸承 12 個｜機械軸封組 3 組" },
  { id: "order", name: "建立維修工單", kind: "write", description: "唯一會改變業務資料的工具，必須先提案與核准。", output: "核准後才可寫入" },
];

const roles: Array<{ id: RoleId; label: string; summary: string }> = [
  { id: "viewer", label: "查看者", summary: "只能使用授權範圍內的三個查詢工具。" },
  { id: "operator", label: "操作者", summary: "可查詢並提出工單，但不能核准自己的提案。" },
  { id: "reviewer", label: "複核者", summary: "可核准有權查看的提案，不能重複計數。" },
  { id: "admin", label: "管理者", summary: "管理帳號與設定，但不能跳過業務核准。" },
];

function ModeBadge({ kind }: { kind: "demo" | "evidence" | "entry" }) {
  const labels = { demo: "離線互動示範", evidence: "歷史實測證據", entry: "真實工作台入口" };
  return <span className={`mode-badge mode-${kind}`}>{labels[kind]}</span>;
}

function PumpDiagram({ active = "bearing" }: { active?: "bearing" | "seal" | "motor" }) {
  return (
    <svg className="pump-diagram" viewBox="0 0 620 330" role="img" aria-labelledby="pump-title pump-desc">
      <title id="pump-title">循環水泵構造示意</title>
      <desc id="pump-desc">馬達經聯軸器連接水泵，軸承目前標示為需要檢查，機械軸封沒有觀察到洩漏。</desc>
      <defs>
        <linearGradient id="pump-body" x1="0" x2="1">
          <stop offset="0" stopColor="#163d39" />
          <stop offset="1" stopColor="#255b51" />
        </linearGradient>
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="9" stdDeviation="10" floodOpacity=".18" />
        </filter>
      </defs>
      <path className="pump-flow" d="M24 166 H105 M515 166 H598" />
      <path className="pump-flow ghost" d="M44 148 l18 18 -18 18 M555 148 l18 18 -18 18" />
      <g filter="url(#shadow)">
        <rect x="84" y="100" width="144" height="132" rx="30" fill="url(#pump-body)" />
        <path d="M105 100V73h70v27M105 232v25h70v-25" fill="none" stroke="#163d39" strokeWidth="18" />
        <circle cx="156" cy="166" r="42" fill="#f4b95f" />
        <path d="M156 131c20 13 29 26 29 39-17-2-33 2-48 13 0-20 6-38 19-52Z" fill="#553c83" />
        <rect x="228" y="143" width="70" height="46" rx="18" fill="#d9c9a8" />
        <circle className={active === "bearing" ? "component-active" : ""} cx="276" cy="166" r="24" fill="#f0e7d7" stroke="#8b623c" strokeWidth="8" />
        <rect x="298" y="112" width="204" height="108" rx="25" fill="#2d2b35" />
        <path d="M326 136h128M326 164h128M326 192h128" stroke="#726f7b" strokeWidth="8" strokeLinecap="round" />
        <rect x="502" y="138" width="31" height="56" rx="10" fill="#a97e46" />
      </g>
      <g className="pump-labels">
        <path d="M157 99V50H91" />
        <text x="21" y="45">葉輪與泵體</text>
        <path d="M276 139V70h-10" />
        <text x="218" y="46">軸承需檢查</text>
        <path d="M397 111V54h70" />
        <text x="472" y="50">馬達</text>
        <path d="M515 195v70h-66" />
        <text x="352" y="290">機械軸封：無洩漏</text>
      </g>
      <circle className="signal-ring" cx="276" cy="166" r="38" />
    </svg>
  );
}

function SectionHeading({ number, eyebrow, title, children }: { number: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <header className="section-heading">
      <div className="section-index" aria-hidden="true">{number}</div>
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{children}</p>
      </div>
    </header>
  );
}

function App() {
  const [profileId, setProfileId] = useState<ProfileId>(() => {
    const saved = sessionStorage.getItem("mcp-showcase-profile");
    return saved === "asset" ? "asset" : "service";
  });
  const [selectedTool, setSelectedTool] = useState<ToolId>("status");
  const [equipment, setEquipment] = useState("EQ-PUMP-001");
  const [queryResult, setQueryResult] = useState("尚未查詢。選擇工具後，結果只會在瀏覽器內產生。");
  const [role, setRole] = useState<RoleId>("operator");
  const [scopeMessage, setScopeMessage] = useState("目前帳號與 Profile 的交集包含 EQ-PUMP-001。" );
  const [proposal, setProposal] = useState(false);
  const [approvals, setApprovals] = useState<string[]>([]);
  const [approvalMessage, setApprovalMessage] = useState("建立提案後才能進入人工核准。" );
  const [attempts, setAttempts] = useState(0);
  const [orderMessage, setOrderMessage] = useState("核准完成後可模擬寫入。" );
  const [configPreview, setConfigPreview] = useState(false);
  const [configApplied, setConfigApplied] = useState(false);
  const [tampered, setTampered] = useState(false);
  const [restoreState, setRestoreState] = useState<RestoreState>("idle");
  const [traceOpen, setTraceOpen] = useState<string | null>(null);
  const [liveMessage, setLiveMessage] = useState("展示狀態已就緒。" );

  const profile = profiles[profileId];
  const approved = approvals.length >= profile.approvals;
  const selectedToolData = tools.find((tool) => tool.id === selectedTool)!;
  const progress = proposal ? (approved ? 3 : 2) : 1;

  useEffect(() => {
    sessionStorage.setItem("mcp-showcase-profile", profileId);
    setApprovals([]);
    setProposal(false);
    setAttempts(0);
    setApprovalMessage(`${profiles[profileId].name}需要 ${profiles[profileId].approvals} 位 reviewer。`);
    setOrderMessage("核准完成後可模擬寫入。" );
  }, [profileId]);

  const traceNodes = useMemo(() => [
    ["request", "收到請求", "合成參數已通過 Schema 驗證。"],
    ["identity", "身分與 scope", `operator ∩ ${profile.name} ∩ EQ-PUMP-001`],
    ["proposal", "凍結提案", proposal ? "參數、設備與政策版本已綁定。" : "等待建立提案。"],
    ["approval", "人工核准", `${approvals.length}/${profile.approvals} 位 reviewer`],
    ["execute", "工具執行", approved && attempts > 0 ? "同一冪等鍵回到 WO-DEMO-001。" : "尚未執行。"],
  ], [profile.name, profile.approvals, proposal, approvals.length, approved, attempts]);

  function chooseProfile(next: ProfileId) {
    setProfileId(next);
    setLiveMessage(`已切換為${profiles[next].name}，欄位與核准規則已更新。`);
  }

  function runTool() {
    if (equipment !== "EQ-PUMP-001") {
      setQueryResult("NOT_FOUND_OR_FORBIDDEN：設備不存在或不在目前帳號與 Profile 的 scope 交集。" );
      setLiveMessage("跨設備查詢已被後端政策故事阻擋。" );
      return;
    }
    if (selectedTool === "order") {
      setQueryResult("寫入工具不能直接執行。請先建立提案並完成獨立核准。" );
      setLiveMessage("建立工單需要先提案與核准。" );
      return;
    }
    setQueryResult(selectedToolData.output);
    setLiveMessage(`${selectedToolData.name}已完成離線示範查詢。`);
  }

  function createProposal() {
    setProposal(true);
    setApprovals([]);
    setApprovalMessage(`提案已凍結；${profile.name}需要 ${profile.approvals} 位不同 reviewer。`);
    setLiveMessage("水泵維修提案已在瀏覽器內建立。" );
  }

  function review(reviewer: "reviewer-a" | "reviewer-b") {
    if (!proposal) {
      setApprovalMessage("請先建立提案。" );
      return;
    }
    if (approvals.includes(reviewer)) {
      setApprovalMessage("拒絕：同一位 reviewer 不能重複計數。" );
      setLiveMessage("重複 reviewer 已被阻擋。" );
      return;
    }
    const next = [...approvals, reviewer];
    setApprovals(next);
    const complete = next.length >= profile.approvals;
    setApprovalMessage(complete ? "核准完成；執行前仍會重新檢查帳號、scope 與版本。" : `已取得 ${next.length}/${profile.approvals}，仍需另一位不同 reviewer。`);
    setLiveMessage(complete ? "核准條件已完成。" : "第一位 reviewer 已核准。" );
  }

  function deny(reason: string) {
    setApprovalMessage(`拒絕：${reason}`);
    setLiveMessage(`操作已被阻擋：${reason}`);
  }

  function execute(mode: "first" | "retry" | "parallel" | "unknown") {
    if (!approved) {
      setOrderMessage("BLOCKED：核准尚未完成，未建立任何工單。" );
      setLiveMessage("寫入被阻擋，沒有建立工單。" );
      return;
    }
    const nextAttempts = attempts + (mode === "parallel" ? 2 : 1);
    setAttempts(nextAttempts);
    const messages = {
      first: "已建立 WO-DEMO-001。這是瀏覽器內的合成工單。",
      retry: "重送命中相同冪等鍵，仍回傳 WO-DEMO-001，沒有第二張工單。",
      parallel: "兩個並行請求合流，唯一約束保留 WO-DEMO-001。",
      unknown: "回應遺失後先查核，找到 WO-DEMO-001；沒有盲目重試。",
    };
    setOrderMessage(messages[mode]);
    setLiveMessage(messages[mode]);
  }

  function runRestore() {
    if (tampered) {
      setRestoreState("blocked");
      setLiveMessage("備份 checksum 不一致，隔離還原已被阻擋。" );
      return;
    }
    setRestoreState("verified");
    setLiveMessage("隔離還原完成，五項權威計數皆為零。" );
  }

  function resetDemo() {
    sessionStorage.removeItem("mcp-showcase-profile");
    setProfileId("service");
    setSelectedTool("status");
    setEquipment("EQ-PUMP-001");
    setQueryResult("尚未查詢。選擇工具後，結果只會在瀏覽器內產生。" );
    setRole("operator");
    setScopeMessage("目前帳號與 Profile 的交集包含 EQ-PUMP-001。" );
    setProposal(false);
    setApprovals([]);
    setAttempts(0);
    setApprovalMessage("建立提案後才能進入人工核准。" );
    setOrderMessage("核准完成後可模擬寫入。" );
    setConfigPreview(false);
    setConfigApplied(false);
    setTampered(false);
    setRestoreState("idle");
    setTraceOpen(null);
    setLiveMessage("已重置介紹站的瀏覽器示範狀態；核心產品未被修改。" );
  }

  return (
    <div className={`app profile-${profileId}`}>
      <a className="skip-link" href="#main">跳到主要內容</a>
      <div className="ambient ambient-one" aria-hidden="true" />
      <div className="ambient ambient-two" aria-hidden="true" />

      <header className="site-header">
        <a className="brand" href="#overview" aria-label="回到作品總覽">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>GATE / 01</strong><small>MCP 工具治理</small></span>
        </a>
        <div className="header-actions">
          <span className="version">Showcase 1.0.0</span>
          <button className="quiet-button" type="button" onClick={resetDemo}>重置示範</button>
        </div>
      </header>

      <nav className="chapter-nav" aria-label="作品章節">
        {chapters.map(([id, number, label]) => <a key={id} href={`#${id}`}><span>{number}</span>{label}</a>)}
      </nav>

      <main id="main">
        <aside className="portfolio-guide" aria-label="三作品分工">
          <p>同一台循環水泵，三個作品接力</p>
          <nav aria-label="三作品導覽">
            <a href="http://127.0.0.1:4178/?v=1.1.0"><strong>作品一：判斷</strong><span>判斷水泵異常與需要補查的資料</span></a>
            <a href="#overview" aria-current="page"><strong>作品二：執行</strong><span>查資料，經人員核准後建立工單</span></a>
            <a href="http://127.0.0.1:4180/?v=1.1.0"><strong>作品三：整理文件</strong><span>核對維修單，保留修正與來源</span></a>
          </nav>
          <small>目前是作品二。各站獨立展示，點連結可依序觀看。</small>
        </aside>
        <section id="overview" className="hero section-shell">
          <div className="hero-copy">
            <div className="badge-row"><ModeBadge kind="demo" /><ModeBadge kind="evidence" /></div>
            <p className="eyebrow">循環水泵異常到結案的 AI 維修閉環</p>
            <h1>AI 可以提議。<br /><em>政策才決定能不能寫入。</em></h1>
            <p className="hero-lead">一台水泵出現震動與軸承溫度偏高後，系統先查資料，再由人員核准，最後只建立一次工單，並留下可追查的證據。</p>
            <div className="hero-actions">
              <a className="button primary" href="#profiles">開始 3 分鐘故事</a>
              <a className="button secondary" href="#evidence">直接看證據</a>
            </div>
            <div className="plain-language">
              <strong>第一次看 MCP？</strong>
              <span>把它想成 AI 使用公司工具的標準插座；這個作品補上插座本身沒有處理的身分、權限、核准與防重複寫入。</span>
            </div>
          </div>
          <div className="hero-visual">
            <div className="visual-topline"><span>EQ-PUMP-001</span><span className="status-dot">需要檢查</span></div>
            <PumpDiagram />
            <div className="signal-cards">
              <article><small>工況</small><strong>高負載</strong></article>
              <article><small>異常</small><strong>持續震動</strong></article>
              <article><small>安全反例</small><strong>無洩漏／火花</strong></article>
            </div>
          </div>
          <div className="hero-stats" aria-label="0.5.0 歷史能力摘要">
            <article><strong>2</strong><span>客戶模式</span></article>
            <article><strong>3 + 1</strong><span>唯讀＋寫入工具</span></article>
            <article><strong>1 / 2</strong><span>核准人數</span></article>
            <article><strong>0</strong><span>還原後權威</span></article>
          </div>
        </section>

        <section id="profiles" className="section-shell content-section">
          <SectionHeading number="02" eyebrow="CUSTOMIZATION" title="同一台水泵，兩種客戶模式">切換的不只是顏色：欄位、scope、核准人數、保存方式與操作重點都會改變。</SectionHeading>
          <div className="profile-layout">
            <div className="profile-switch" role="group" aria-label="選擇客戶模式">
              {(Object.keys(profiles) as ProfileId[]).map((id) => (
                <button key={id} type="button" aria-pressed={profileId === id} onClick={() => chooseProfile(id)}>
                  <span>{profiles[id].short}</span><strong>{profiles[id].name}</strong><small>{profiles[id].description}</small>
                </button>
              ))}
            </div>
            <article className="profile-detail card-surface">
              <div className="card-title"><ModeBadge kind="demo" /><span>{profile.color}介面</span></div>
              <h3>{profile.name}</h3>
              <p>{profile.description}</p>
              <div className="fact-grid">
                <div><small>核准</small><strong>{profile.approvals} 人</strong></div>
                <div><small>示範保存</small><strong>{profile.retention}</strong></div>
                <div><small>設備 scope</small><strong>{profile.scope.length} 台</strong></div>
              </div>
              <div className="field-cloud" aria-label={`${profile.name}必填欄位`}>
                {profile.fields.map((field) => <span key={field}>{field}</span>)}
              </div>
            </article>
          </div>
        </section>

        <section id="tools" className="section-shell content-section">
          <SectionHeading number="03" eyebrow="TOOL CATALOG" title="先查三次，再申請一次寫入">工具描述輸入與輸出；真正的產品使用 MCP stdio，這裡只在瀏覽器中重播固定合成結果。</SectionHeading>
          <div className="tool-grid">
            {tools.map((tool, index) => (
              <button key={tool.id} type="button" className={`tool-card ${selectedTool === tool.id ? "selected" : ""} ${tool.kind}`} onClick={() => setSelectedTool(tool.id)} aria-pressed={selectedTool === tool.id}>
                <span className="tool-number">0{index + 1}</span><span className={`tool-kind ${tool.kind}`}>{tool.kind === "read" ? "唯讀" : "核准後寫入"}</span>
                <strong>{tool.name}</strong><small>{tool.description}</small>
              </button>
            ))}
          </div>
          <div className="workbench card-surface">
            <div className="workbench-head"><div><ModeBadge kind="demo" /><h3>{selectedToolData.name}</h3></div><code>{selectedToolData.kind === "read" ? "read_tool" : "write_tool"}</code></div>
            <div className="form-grid">
              <label>設備編號<select value={equipment} onChange={(event) => setEquipment(event.target.value)}><option>EQ-PUMP-001</option><option>EQ-CHILLER-004</option></select></label>
              <label>工況<input value="高負載" readOnly /></label>
              <label>異常摘要<input value="持續震動，軸承溫度偏高" readOnly /></label>
              <label>安全反例<input value="未發現洩漏、火花或焦味" readOnly /></label>
            </div>
            <div className="action-row"><button type="button" className="button primary" onClick={runTool}>執行離線示範</button><span>沒有 MCP 或 API 請求</span></div>
            <output className={queryResult.startsWith("NOT") ? "result blocked" : "result"} aria-live="polite">{queryResult}</output>
          </div>
        </section>

        <section id="scope" className="section-shell content-section">
          <SectionHeading number="04" eyebrow="IDENTITY × POLICY" title="權限不是藏按鈕，而是後端交集">角色、帳號設備範圍、Profile 範圍與工具政策必須同時允許；不存在與無權限使用同一外部訊息。</SectionHeading>
          <div className="scope-layout">
            <div className="role-list" role="group" aria-label="預覽角色">
              {roles.map((item) => <button key={item.id} type="button" aria-pressed={role === item.id} onClick={() => { setRole(item.id); setScopeMessage(item.summary); }}>{item.label}<small>{item.summary}</small></button>)}
            </div>
            <article className="scope-visual card-surface">
              <ModeBadge kind="demo" />
              <div className="scope-rings" aria-label="權限交集示意">
                <div className="ring account">帳號 scope<div className="ring profile">Profile<div className="ring policy">工具政策<strong>EQ-PUMP-001</strong></div></div></div>
              </div>
              <p className="role-output"><strong>{roles.find((item) => item.id === role)?.label}</strong>：{scopeMessage}</p>
              <div className="action-row wrap">
                <button type="button" className="button secondary" onClick={() => setScopeMessage("EQ-PUMP-001 位於四層交集，可以查詢。" )}>檢查水泵權限</button>
                <button type="button" className="button danger" onClick={() => { setEquipment("EQ-CHILLER-004"); setScopeMessage("NOT_FOUND_OR_FORBIDDEN：不能藉由直接 ID 枚舉設備。" ); setLiveMessage("跨設備越權已被阻擋。" ); }}>嘗試跨設備</button>
              </div>
            </article>
          </div>
        </section>

        <section id="approval" className="section-shell content-section">
          <SectionHeading number="05" eyebrow="HUMAN GATE" title="寫入之前，先凍結提案再獨立核准">核准綁定工具、參數、設備、資料版本與政策版本；內容改動、過期或撤權都會失效。</SectionHeading>
          <div className="approval-layout">
            <article className="proposal-card card-surface">
              <div className="card-title"><ModeBadge kind="demo" /><span>{profile.name}</span></div>
              <h3>水泵停機檢查提案</h3>
              <dl><div><dt>設備</dt><dd>EQ-PUMP-001</dd></div><div><dt>摘要</dt><dd>高負載持續震動，軸承溫度偏高</dd></div><div><dt>安全訊號</dt><dd>無洩漏、火花或焦味</dd></div><div><dt>維護時段</dt><dd>{profileId === "asset" ? "需填寫並確認" : "可選"}</dd></div></dl>
              <button type="button" className="button primary full" onClick={createProposal}>{proposal ? "重新建立新版本提案" : "建立並凍結提案"}</button>
            </article>
            <article className="approval-track card-surface">
              <div className="progress-track" aria-label={`核准流程第 ${progress} 階段`}><i className="done">提案</i><i className={proposal ? "done" : ""}>凍結</i><i className={approved ? "done" : ""}>核准</i><i>執行前重驗</i></div>
              <h3>{approvals.length}/{profile.approvals} 位 reviewer</h3>
              <div className="reviewers"><button type="button" onClick={() => review("reviewer-a")}>Reviewer A 核准</button>{profile.approvals === 2 && <button type="button" onClick={() => review("reviewer-b")}>Reviewer B 核准</button>}</div>
              <div className="denial-actions"><button type="button" onClick={() => deny("提出者不能審核自己的提案。")}>模擬自審</button><button type="button" onClick={() => review("reviewer-a")}>重複 Reviewer A</button><button type="button" onClick={() => deny("核准後參數已改動，必須建立新版本。")}>修改已核准參數</button></div>
              <output className={`result ${approvalMessage.startsWith("拒絕") ? "blocked" : ""}`} aria-live="polite">{approvalMessage}</output>
            </article>
          </div>
        </section>

        <section id="idempotency" className="section-shell content-section dark-section">
          <SectionHeading number="06" eyebrow="EXACTLY ONE ORDER" title="按兩次，也只能有一張工單">冪等鍵、資料庫交易與唯一約束一起工作；回應遺失時先查核，不盲目重試。</SectionHeading>
          <div className="idempotency-layout">
            <div className="request-stream card-surface dark-card" aria-label="多個請求合流成一張工單">
              <div className="request-lines"><span>第一次送出</span><span>使用者重送</span><span>並行請求</span></div>
              <div className="gate-node">idempotency<br /><strong>PUMP-DEMO-001</strong></div>
              <div className="single-order"><small>唯一結果</small><strong>{attempts > 0 ? "WO-DEMO-001" : "等待核准"}</strong><span>{attempts} 次請求嘗試</span></div>
            </div>
            <article className="card-surface dark-card controls-card">
              <div className="button-grid"><button type="button" onClick={() => execute("first")}>第一次送出</button><button type="button" onClick={() => execute("retry")}>重送同一請求</button><button type="button" onClick={() => execute("parallel")}>模擬並行</button><button type="button" onClick={() => execute("unknown")}>模擬結果不明</button></div>
              <output className={`result ${orderMessage.startsWith("BLOCKED") ? "blocked" : "success"}`} aria-live="polite">{orderMessage}</output>
            </article>
          </div>
        </section>

        <section id="configuration" className="section-shell content-section">
          <SectionHeading number="07" eyebrow="VERSIONED CUSTOMIZATION" title="客製化可以改流程，不能改掉安全底線">設定要經過草稿、驗證、差異預覽、獨立核准與交易式套用；還原會建立新草稿。</SectionHeading>
          <div className="config-layout">
            <article className="config-card card-surface"><small>目前版本</small><h3>{profile.name} v1</h3><ul><li>核准：{profile.approvals} 人</li><li>保存：{profile.retention}</li><li>水泵欄位：{profile.fields.length} 個</li><li>設備範圍：{profile.scope.join("、")}</li></ul></article>
            <div className="config-arrow" aria-hidden="true">→</div>
            <article className="config-card candidate card-surface"><small>候選草稿</small><h3>{profile.name} v2</h3><ul><li>新增：軸承溫度來源說明</li><li>風險理由最少 16 字</li><li>權限範圍沒有擴大</li><li>舊提案維持原版本並失效</li></ul></article>
            <article className="diff-panel card-surface">
              <div className="action-row wrap"><button type="button" className="button secondary" onClick={() => setConfigPreview(!configPreview)}>預覽差異</button><button type="button" className="button primary" disabled={!configPreview} onClick={() => { setConfigApplied(true); setLiveMessage("離線設定套用示範完成，核心工作台未被修改。" ); }}>模擬核准後套用</button></div>
              {configPreview && <div className="diff-lines"><span className="plus">＋ bearing_temperature_source：必填</span><span className="plus">＋ review_reason_min：16</span><span className="same">＝ device_scope：未擴大</span></div>}
              {configApplied && <p className="inline-success">離線示範已套用；真實工作台設定沒有改動。</p>}
            </article>
          </div>
        </section>

        <section id="restore" className="section-shell content-section">
          <SectionHeading number="08" eyebrow="DATA WITHOUT AUTHORITY" title="備份資料關係，不帶回執行權">四段 migration 使用固定 checksum；隔離還原不建立 Session、不復活核准，也不重放 MCP 工具。</SectionHeading>
          <div className="ledger card-surface">
            {["001-p2c-core", "002-p2d1-retention", "003-p2d2-profile-versions", "004-p2d3-backup-restore"].map((item, index) => <div key={item}><span>0{index + 1}</span><strong>{item}</strong><small>已套用 · checksum 一致</small></div>)}
          </div>
          <div className="restore-layout">
            <article className="backup-card include card-surface"><h3>備份會包含</h3><ul><li>Schema 與 migration metadata</li><li>去內容的 Profile 關係</li><li>工單與 Trace 統計</li></ul></article>
            <article className="backup-card exclude card-surface"><h3>一律排除</h3><ul><li>密碼、Session、CSRF</li><li>原始工具輸入與工單內文</li><li>有效核准與可重放狀態</li></ul></article>
            <article className="restore-control card-surface"><ModeBadge kind="demo" /><label className="check-row"><input type="checkbox" checked={tampered} onChange={(event) => { setTampered(event.target.checked); setRestoreState("idle"); }} />模擬備份遭竄改</label><button type="button" className="button primary full" onClick={runRestore}>建立隔離還原</button><output className={`restore-output ${restoreState}`} aria-live="polite">{restoreState === "idle" && "尚未執行還原。"}{restoreState === "blocked" && "BLOCKED：checksum 不一致，沒有建立還原環境。"}{restoreState === "verified" && <><strong>零權威驗證通過</strong><span>Session 0 · 授權上下文 0 · 有效核准 0 · 自動重放 0 · MCP 呼叫 0</span></>}</output></article>
          </div>
        </section>

        <section id="trace" className="section-shell content-section dark-section">
          <SectionHeading number="09" eyebrow="TRACE & ISOLATION" title="每一步都能追查，但不公開原始內容">點開節點可查看去識別理由；正式產品、E2E、備份、還原與 Showcase 不共用執行狀態。</SectionHeading>
          <div className="trace-layout">
            <div className="trace-line" aria-label="工具執行 Trace">
              {traceNodes.map(([id, label, detail], index) => <button type="button" key={id} className={traceOpen === id ? "active" : ""} onClick={() => setTraceOpen(traceOpen === id ? null : id)}><span>{index + 1}</span><strong>{label}</strong>{traceOpen === id && <small>{detail}</small>}</button>)}
            </div>
            <article className="isolation-card card-surface dark-card"><h3>五個隔離區</h3><div className="isolation-grid">{["核心產品", "E2E", "去內容備份", "唯讀還原", "Showcase"].map((item, index) => <div key={item}><span>0{index + 1}</span>{item}</div>)}</div><button type="button" onClick={() => setLiveMessage("跨環境寫入已阻擋：Showcase 沒有產品憑證、API client 或資料庫連線。" )}>嘗試跨環境寫入</button><p>只有語意與公開證據摘要可以跨區，帳號、工單與核准都不共享。</p></article>
          </div>
        </section>

        <section id="evidence" className="section-shell content-section evidence-section">
          <SectionHeading number="10" eyebrow="EVIDENCE, NOT PROMISES" title="做過什麼、沒做什麼，都放在同一頁">以下是 0.5.0 在 {evidence.verified_on} 的本機合成資料歷史證據，不是目前工作台即時狀態。</SectionHeading>
          <div className="evidence-layout">
            <article className="evidence-board card-surface">
              <div className="card-title"><ModeBadge kind="evidence" /><span>核心 {evidence.core_version}</span></div>
              <div className="metric-grid"><div><strong>{evidence.checks.backend.passed}/{evidence.checks.backend.passed + evidence.checks.backend.failed}</strong><span>後端</span></div><div><strong>{evidence.checks.frontend_component.passed}/{evidence.checks.frontend_component.passed + evidence.checks.frontend_component.failed}</strong><span>前端</span></div><div><strong>{evidence.checks.e2e.passed}/{evidence.checks.e2e.passed + evidence.checks.e2e.failed}</strong><span>E2E</span></div><div><strong>{evidence.migration.applied}</strong><span>Migration</span></div></div>
              <div className="milestone-row">{evidence.milestones.map((item) => <span key={item.id}>{item.id}<small>{item.version}</small></span>)}</div>
              <p>{evidence.data_notice}</p>
            </article>
            <article className="limits-board card-surface"><h3>沒有宣稱</h3><ul>{evidence.not_claimed.map((item) => <li key={item}>{item}</li>)}</ul></article>
          </div>
          <div className="download-panel">
            <div><ModeBadge kind="evidence" /><h3>帶走可公開摘要</h3><p>下載檔來自同一白名單產生器，不包含帳號、Session、完整 Trace、工單內文或私人路徑。</p></div>
            <div className="action-row wrap"><a className="button secondary" download href="/downloads/evidence-summary.json">下載 JSON</a><a className="button secondary" download href="/downloads/作品證據摘要.md">下載 Markdown</a><button type="button" className="button secondary" onClick={() => window.print()}>列印摘要</button></div>
          </div>
          <div className="workbench-entry">
            <div><ModeBadge kind="entry" /><h3>想操作真正的本機產品？</h3><p>本站不探查服務狀態。請先依 README 啟動工作台，再由你主動開啟；`127.0.0.1` 指的是你自己的電腦。</p><code>http://127.0.0.1:8130/</code></div>
            <a className="button primary" href="http://127.0.0.1:8130/" target="_blank" rel="noreferrer" data-real-workbench>使用者主動開啟工作台</a>
          </div>
        </section>
      </main>

      <footer><div><strong>GATE / 01</strong><span>MCP 工具治理 · 循環水泵合成案例</span></div><p>本機作品展示｜繁體中文｜不含外部必要資源</p></footer>
      <div className="live-region" role="status" aria-live="polite">{liveMessage}</div>
    </div>
  );
}

export default App;

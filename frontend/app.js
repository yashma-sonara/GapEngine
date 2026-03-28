const categories = ["Entertainment", "Travel", "Tech", "Consumer", "Finance", "Health"];
const demos = [
  { category: "Travel", subject: "Disney Cruise", claim: "Is it worth the price?" },
  { category: "Tech", subject: "Notion AI", claim: "Does it actually save teams time?" },
  { category: "Entertainment", subject: "MasterClass", claim: "Is it worth paying annually?" },
];

function App() {
  const { useMemo, useState } = React;
  const [form, setForm] = useState(demos[0]);
  const [events, setEvents] = useState([]);
  const [report, setReport] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");

  const progressEvents = useMemo(
    () => events.filter((event) => event.kind === "stage" || event.kind === "tinyfish_event"),
    [events]
  );

  async function runAnalysis(event) {
    event.preventDefault();
    setIsRunning(true);
    setEvents([]);
    setReport(null);
    setError("");

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: form.category,
          subject: form.subject,
          claim_or_question: form.claim,
        }),
      });

      if (!response.ok || !response.body) throw new Error("Failed to start analysis stream.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const parsed = parseSseChunk(chunk);
          if (!parsed) continue;
          if (parsed.event === "final_report") {
            setReport(parsed.data);
          } else if (parsed.event === "error") {
            setError(parsed.data.message || "Unknown error");
          } else {
            setEvents((current) => [...current, { kind: parsed.event, ...parsed.data }]);
          }
        }
      }
    } catch (err) {
      setError(err.message || "Unexpected client error.");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">GapEngine x TinyFish</p>
          <h1>Cut through marketing gloss with live web evidence.</h1>
          <p className="lede">
            Watch GapEngine scan official claims and independent feedback in real time, then score
            the truth gap across five dimensions.
          </p>
        </div>
        <div className="hero-orb" />
      </section>

      <section className="panel panel-form">
        <div className="demo-row">
          {demos.map((demo) => (
            <button key={demo.subject} className="chip" onClick={() => setForm(demo)} type="button">
              {demo.subject}
            </button>
          ))}
        </div>

        <form onSubmit={runAnalysis}>
          <div className="form-grid">
            <label>
              <span>Category</span>
              <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>
                {categories.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Subject</span>
              <input value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} placeholder="Disney Cruise" />
            </label>
          </div>

          <label>
            <span>Claim or question</span>
            <textarea rows="3" value={form.claim} onChange={(event) => setForm({ ...form, claim: event.target.value })} placeholder="Is it worth the price?" />
          </label>

          <button className="primary-button" disabled={isRunning} type="submit">
            {isRunning ? "Scanning live web evidence..." : "Run live analysis"}
          </button>
        </form>
      </section>

      <section className="grid">
        <article className="panel panel-progress">
          <div className="panel-header">
            <h2>Live TinyFish stream</h2>
            <span className={`status-dot ${isRunning ? "active" : ""}`} />
          </div>
          <div className="timeline">
            {progressEvents.length === 0 && <p className="muted">No events yet. Start a run to watch live progress.</p>}
            {progressEvents.map((event, index) => (
              <div className="timeline-item" key={`${event.kind}-${index}`}>
                <div className="timeline-type">{event.kind}</div>
                <div className="timeline-body">
                  {event.message && <p>{event.message}</p>}
                  {event.tinyfish_event && (
                    <>
                      <p><strong>{event.tinyfish_event.type || "EVENT"}</strong></p>
                      {event.tinyfish_event.purpose && <p>{event.tinyfish_event.purpose}</p>}
                      {event.tinyfish_event.streaming_url && (
                        <a href={event.tinyfish_event.streaming_url} target="_blank" rel="noreferrer">Open browser stream</a>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
          {error && <div className="error-box">{error}</div>}
        </article>

        <article className="panel panel-score">
          <div className="panel-header"><h2>Gap verdict</h2></div>
          {!report && <p className="muted">The final verdict appears here after TinyFish finishes.</p>}
          {report && (
            <>
              <div className="score-row">
                <div className="score-ring"><span>{report.result.gap_score}</span><small>/ 10</small></div>
                <div>
                  <p className="verdict">{report.result.verdict}</p>
                  <p className="muted">Five dimensions averaged into one credibility gap score.</p>
                </div>
              </div>
              <div className="bars">
                {Object.entries(report.result.dimension_scores).map(([label, value]) => (
                  <div className="bar-row" key={label}>
                    <div className="bar-label"><span>{label}</span><span>{value}/10</span></div>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${value * 10}%` }} /></div>
                  </div>
                ))}
              </div>
            </>
          )}
        </article>
      </section>

      <section className="grid">
        <article className="panel">
          <div className="panel-header"><h2>Official claims</h2></div>
          {report?.result?.official_claims?.map((item, index) => <div className="evidence-card" key={index}>{item}</div>) || <p className="muted">Official brand claims will appear here.</p>}
        </article>
        <article className="panel">
          <div className="panel-header"><h2>Independent signals</h2></div>
          {report?.result?.independent_signals?.map((item, index) => <div className="evidence-card danger" key={index}>{item}</div>) || <p className="muted">Counter-signals from reviews and forums will appear here.</p>}
        </article>
      </section>

      <section className="grid">
        <article className="panel">
          <div className="panel-header"><h2>Official source evidence</h2></div>
          <EvidenceList items={report?.evidence?.official_sources?.items || []} />
        </article>
        <article className="panel">
          <div className="panel-header"><h2>Independent source evidence</h2></div>
          <EvidenceList items={report?.evidence?.independent_sources?.items || []} />
        </article>
      </section>

      <section className="panel">
        <div className="panel-header"><h2>Source-by-source scan</h2></div>
        <div className="source-grid">
          {Object.values(report?.source_sections || {}).map((section) => (
            <div className="source-column" key={section.key}>
              <div className="source-column-head">
                <strong>{section.label}</strong>
                <p className="muted">{section.summary}</p>
              </div>
              <EvidenceList items={section.items || []} />
            </div>
          ))}
          {!Object.values(report?.source_sections || {}).length && (
            <p className="muted">Each public source scan will appear here: careers, LinkedIn, Google News/Search, and Reddit.</p>
          )}
        </div>
      </section>
    </main>
  );
}

function EvidenceList({ items }) {
  if (!items.length) return <p className="muted">Evidence cards will appear here after a run.</p>;
  return items.map((item, index) => (
    <div className="source-card" key={index}>
      <div className="source-head"><strong>{item.title}</strong><span>{item.source}</span></div>
      <p>{item.snippet}</p>
      <a href={item.url} target="_blank" rel="noreferrer">Open source</a>
    </div>
  ));
}

function parseSseChunk(chunk) {
  const lines = chunk.split("\n");
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);

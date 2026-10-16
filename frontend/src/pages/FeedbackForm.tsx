/* The page customers open from a feedback email or text. No sign-in: the link is the key. */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

interface Info { company: string; name: string; kind: string; period: string; job: string; answered: boolean; ratings: Record<string, string> }

export default function FeedbackForm() {
  const { token } = useParams();
  const [info, setInfo] = useState<Info | null>(null);
  const [score, setScore] = useState<number | null>(null);
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [done, setDone] = useState<{ review_url: string } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`/api/public/feedback/${token}`).then(async (r) => (r.ok ? setInfo(await r.json()) : setError("This link isn't valid any more.")));
  }, [token]);
  const send = async () => {
    const r = await fetch(`/api/public/feedback/${token}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ score, ratings, comment }) });
    if (r.ok) setDone(await r.json()); else setError((await r.json()).detail ?? "Something went wrong");
  };
  const month = info?.period ? new Date(info.period + "-01T00:00:00").toLocaleDateString("en-AU", { month: "long", year: "numeric" }) : "";
  return (
    <main className="feedback-page">
      <div className="fb-card">
        {!info && <p>{error || "Loading…"}</p>}
        {info && (info.answered || done) ? (
          <>
            <h1>Thanks{info.name ? `, ${info.name.split(" ")[0]}` : ""}!</h1>
            <p>Your feedback goes straight to the team at {info.company}.</p>
            {done?.review_url && (
              <div className="fb-review">
                <p>Glad we did a good job. Would you share that on Google? It really helps a local business.</p>
                <a className="btn primary big-btn" href={done.review_url} target="_blank" rel="noreferrer"
                   onClick={() => fetch(`/api/public/feedback/${token}/review-click`, { method: "POST" })}>Leave a Google review</a>
              </div>
            )}
          </>
        ) : info && (
          <>
            <h1>{info.company}</h1>
            <p>{info.kind === "monthly" ? `How did we go on your jobs in ${month}?` : `How did we go${info.job ? ` on ${info.job}` : ""}?`}</p>
            <h2>How likely are you to recommend us to a friend or colleague?</h2>
            <div className="nps-scale">
              {Array.from({ length: 11 }, (_, i) => (
                <button key={i} className={score === i ? "on" : ""} onClick={() => setScore(i)} aria-label={`${i} out of 10`}>{i}</button>
              ))}
            </div>
            <div className="nps-ends"><span>Not likely</span><span>Very likely</span></div>
            {Object.entries(info.ratings).map(([k, label]) => (
              <div key={k} className="fb-rating"><span>{label}</span>
                <div>{[1, 2, 3, 4, 5].map((n) => <button key={n} className={(ratings[k] ?? 0) >= n ? "star on" : "star"} onClick={() => setRatings({ ...ratings, [k]: n })} aria-label={`${n} stars`}>★</button>)}</div>
              </div>
            ))}
            <textarea rows={4} placeholder="Anything we did well, or could do better?" value={comment} onChange={(e) => setComment(e.target.value)} />
            <button className="primary big-btn" disabled={score === null} onClick={send}>Send</button>
            {error && <p className="error">{error}</p>}
          </>
        )}
      </div>
    </main>
  );
}

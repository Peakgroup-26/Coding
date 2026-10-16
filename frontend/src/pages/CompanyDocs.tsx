/* Company documents: policies, SWMS, licences, insurance, templates and manuals. Marked documents show on the team's phones. */
import { Docs } from "./JobHub";

export default function CompanyDocs() {
  return (
    <main className="page">
      <h1>Company documents</h1>
      <Docs jobId={null} />
    </main>
  );
}

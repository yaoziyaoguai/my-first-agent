/** REAL-EVIDENCE 001-008 详情模型 */

import evidenceJson from "./evidenceDetails.json";

export type EvidenceStatus =
  | "credible"
  | "credible-with-caveats"
  | "partial-credible";

export interface EvidenceDetail {
  id: string;
  capability: string;
  status: EvidenceStatus;
  latestDogfood: string;
  latestCommit: string;
  caveats: string;
  nextAction: string;
}

interface EvidenceConfig {
  version: string;
  details: EvidenceDetail[];
}

export function loadEvidenceDetails(): EvidenceDetail[] {
  const config = evidenceJson as EvidenceConfig;
  return config.details;
}

export function getEvidenceById(id: string): EvidenceDetail | undefined {
  const details = loadEvidenceDetails();
  return details.find((d) => d.id === id);
}

import { canDoSkill } from "./mjeshtrit";
import type { Report, User } from "./api";

/** Icon per fixer level (levels come from the server by verified fixes). */
export const LEVEL_ICON: Record<string, string> = { starter: "🌱", helper: "🧤", fixer: "🛠️", hero: "🦸", legend: "🏆" };

/** Hours (rounded up) until a taken job goes back to the map. */
export const hoursLeft = (deadline: string | null | undefined) =>
  deadline ? Math.max(0, Math.ceil((new Date(deadline).getTime() - Date.now()) / 3_600_000)) : null;

/**
 * Can this user take this report as a neighbour job, and if not, why not?
 * Any resident can take any job, in any neighbourhood, unless the AI check says it isn't safe.
 * "ok" | "unsafe" (the AI said no) | "crew" (no AI verdict, and the category needs the city) |
 * null (not a job: fixed, already taken, or not a resident)
 */
export function jobState(r: Report, user: User | null): "ok" | "unsafe" | "crew" | "flagged" | "mjeshter" | null {
  if (!user || user.role !== "citizen" || r.status !== "reported" || r.claimed_by) return null;
  if (r.neighbour_fixable) return "ok";
  if (r.flagged) return "flagged";
  // A skilled job: verified mjeshtrit with the skill can take it; everyone else can ask one.
  if (r.skill_needed) return canDoSkill(user, r.skill_needed) ? "ok" : "mjeshter";
  return r.ai_neighbour_safe === false || r.ai_is_problem === false ? "unsafe" : "crew";
}

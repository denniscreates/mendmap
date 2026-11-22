import type { Report, User } from "./api";

/** Skills a mjeshtër (skilled volunteer) can have, with their icons. */
export const SKILLS = ["plumbing", "electrics", "building", "painting", "carpentry", "gardening", "welding"] as const;
export type Skill = (typeof SKILLS)[number];
export const SKILL_ICON: Record<string, string> = {
  plumbing: "🔧", electrics: "⚡", building: "🧱", painting: "🎨", carpentry: "🪚", gardening: "🌳", welding: "🔥", any: "🧰",
};

/** When a mjeshtër is free to help. */
export const DAYS = ["weekday_evenings", "saturday", "sunday", "holidays"] as const;

/** Can this user take a skilled job that needs `need`? */
export const canDoSkill = (user: User | null, need: string | null | undefined) => {
  const skills = user?.mjeshter_skills ?? [];
  return !!need && skills.length > 0 && (need === "any" || skills.includes(need));
};

export const isSkillJob = (r: Report) => !!r.skill_needed;

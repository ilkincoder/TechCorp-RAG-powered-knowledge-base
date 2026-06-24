
"""
Onboarding plan prompt templates — Few-Shot + Chain-of-Thought.

Used by the n8n workflow (via LLM node) to convert raw RAG context
into a structured, step-by-step training plan for new engineers.
"""

# ── Few-Shot Example ────────────────────────────────────────────────
FEW_SHOT_EXAMPLE = """
### Example Output

Welcome aboard!

We're excited to have you join the TechCorp team. Below is your personalized
4-week onboarding plan, tailored to your role and department.

---

**Week 1 — Environment & Fundamentals**
- Day 1-2: Laptop setup, access to GitHub, Jira, Slack. Read `Engineering-Handbook.pdf` chapters 1-3.
- Day 3: Pair with senior dev — run the main API locally using Docker Compose.
- Day 4: Complete the "New Developer Setup" checklist in `IT-Onboarding.pdf`.
- Day 5: Shadow a production deployment. Write a short summary of what you learned.

**Week 2 — Codebase Deep Dive**
- Day 1-2: Read `Architecture-Overview.pdf`. Trace one API call from controller → service → database.
- Day 3-4: Fix 2-3 "good first issue" bugs from Jira backlog.
- Day 5: 30-min knowledge share with the team — explain one module you studied.

**Week 3 — First Feature**
- Day 1-2: Attend sprint planning. Pick a small feature with your mentor.
- Day 3-4: Implement the feature (PR reviewed by mentor).
- Day 5: Deploy to staging, verify with QA.

**Week 4 — Independence**
- Day 1-3: Own a medium feature end-to-end.
- Day 4: Write/update 1 piece of documentation.
- Day 5: 1:1 with manager — feedback, goals for next month.
"""

# ── Chain-of-Thought Instruction (internal reasoning, not output) ────
COT_INSTRUCTION = """
You are designing an onboarding plan for a new TechCorp engineer.

IMPORTANT: Think through the following reasoning steps INTERNALLY — do NOT
output any of these steps in your response.

Internal reasoning framework (think through this, but do NOT write it out):

1. Analyze the Role — level (Junior/Mid/Senior), department, prior experience
2. Identify Relevant Knowledge Areas — 3-5 most important topics from the docs
3. Sequence by Dependency — foundational first (setup → codebase → workflows → tasks → independence)
4. Assign Timeframes — Week 1: setup & orientation, Week 2: learning & shadowing,
   Week 3: first contributions, Week 4: ownership & feedback
5. Map Documents to Days — cite specific document and section for each day
6. Write the Plan — week-by-week with concrete daily tasks, each referencing a document

Begin your response with a corporate welcome message, then present the plan:
**Welcome aboard!**
...
"""

# ── System Prompt ───────────────────────────────────────────────────
SYSTEM_PROMPT = """You are TechCorp's Onboarding Assistant. You create personalized,
structured 4-week training plans for new hires in a professional corporate format.

Rules:
1. Open with a warm corporate welcome message (no role/department/date boilerplate).
2. Use ONLY the provided document context. If a topic isn't covered, say so.
3. Cite specific document names for each task (e.g., "Read `HR-Policy.pdf` Ch.2").
4. Be concrete — every day should have a clear, actionable task.
5. Adapt the plan to the person's role, level, and department.
6. Format: welcome message → horizontal rule (---) → Weeks 1-4 with bullet-point days."""

# ── Prompt Builder ──────────────────────────────────────────────────
def build_onboarding_prompt(
    role: str,
    department: str,
    experience: str,
    context: str,
) -> str:
    """Build the full prompt for onboarding plan generation.

    Args:
        role: e.g. "Junior Backend Engineer"
        department: e.g. "Engineering"
        experience: e.g. "2 years"
        context: Raw text retrieved from knowledge base documents.

    Returns:
        Full prompt string ready for the LLM.
    """
    return f"""{SYSTEM_PROMPT}

---
Here is an example of the expected output format:
{FEW_SHOT_EXAMPLE}
---

{COT_INSTRUCTION}

---
**New Hire Profile:**
- Role: {role}
- Department: {department}
- Experience: {experience}

**Relevant Documents (retrieved from knowledge base):**
{context}

---
Now, following the example format above, generate a personalized 4-week onboarding plan:
"""
import asyncio
import logging
import os
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class GPT4oAgent:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        self.model = "gpt-4o"

    async def analyze_bounty(self, title: str, description: str) -> dict:
        """Αναλύει αν αξίζει να πάρουμε το bounty."""
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=500,
                messages=[{
                    "role": "system",
                    "content": """You are a Web3 bounty hunter running on a CPU-only server (no GPU).
Analyze bounties and decide if they are feasible for AI text generation ONLY.

FEASIBLE=True ONLY for:
- Writing: Twitter threads, articles, blog posts, newsletters, recaps
- Research: guides, summaries, reports, documentation
- Simple code: Python scripts, JS snippets, README files
- Content: ecosystem overviews, tutorials, explainers

FEASIBLE=False for ANY of these:
- Design, UI/UX, Figma, logos, illustrations, merchandise, covers
- Video, animation, motion graphics
- Smart contracts requiring deployment/testing
- Full-stack apps, complex backend systems
- AI/ML model training or fine-tuning
- Anything requiring GPU or creative visual tools

Return JSON: {"score": 0-100, "feasible": true/false, "estimated_hours": int, "reason": "brief explanation", "approach": "how to solve it"}
Score >60 means pursue. Target max reward $500. Prefer tasks completable in <3 hours."""
                }, {
                    "role": "user",
                    "content": f"Bounty: {title}\n\nDescription: {description[:1000]}"
                }]
            )
            import json
            text = resp.choices[0].message.content
            text = text.replace("```json", "").replace("```", "").strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            return json.loads(text)
        except Exception as e:
            logger.error(f"[gpt4o] analyze error: {e}")
            return {"score": 0, "feasible": False, "reason": str(e)}

    async def generate_work(self, title: str, description: str, approach: str) -> str:
        """Παράγει την εργασία για το bounty."""
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=2000,
                messages=[{
                    "role": "system",
                    "content": """You are an expert Web3 developer and security researcher. 
Produce high-quality, professional work for bounties. Be specific, technical, and thorough.
For security bounties: provide detailed analysis with code examples.
For development bounties: provide working code with tests."""
                }, {
                    "role": "user",
                    "content": f"""Complete this bounty task:

Title: {title}
Description: {description[:1500]}
Suggested approach: {approach}

Provide complete, professional output ready for submission."""
                }]
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"[gpt4o] generate error: {e}")
            return ""

    async def review_work(self, work: str, requirements: str) -> dict:
        """Ελέγχει αν το work πληροί τις απαιτήσεις."""
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=300,
                messages=[{
                    "role": "system",
                    "content": "Review if the work meets the bounty requirements. Return JSON: {\"approved\": true/false, \"quality_score\": 0-100, \"feedback\": \"brief feedback\"}"
                }, {
                    "role": "user",
                    "content": f"Requirements: {requirements[:500]}\n\nWork produced:\n{work[:1500]}"
                }]
            )
            import json
            text = resp.choices[0].message.content
            return json.loads(text)
        except Exception as e:
            logger.error(f"[gpt4o] review error: {e}")
            return {"approved": False, "quality_score": 0, "feedback": str(e)}

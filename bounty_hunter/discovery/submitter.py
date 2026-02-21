import asyncio
import logging
import os
import json
import httpx
from .models.bounty import Bounty, BountyStatus

logger = logging.getLogger(__name__)

class BountySubmitter:
    def __init__(self, queue):
        self.queue = queue
        self.github_token = os.environ.get("GITHUB_TOKEN", "")
        self.evm_wallet = os.environ.get("EVM_WALLET", "")
        self.sol_wallet = os.environ.get("SOLANA_WALLET", "")

    async def audit_work(self, bounty: Bounty, work: str) -> dict:
        from openai import AsyncOpenAI
        import json
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o",
                max_tokens=400,
                messages=[{
                    "role": "system",
                    "content": 'You are a strict quality auditor. Return JSON: {"approved": true/false, "score": 0-100, "reason": "...", "improvements": "..."}'
                }, {
                    "role": "user",
                    "content": f"Bounty: {bounty.title}\nRequirements: {(bounty.description or '')[:800]}\n\nWork:\n{work[:2000]}"
                }]
            )
            text = resp.choices[0].message.content.replace("```json","").replace("```","").strip()
            result = json.loads(text)
            logger.info(f"[audit] Score: {result.get('score')}/100 | Approved: {result.get('approved')}")
            return result
        except Exception as e:
            logger.error(f"[audit] Error: {e}")
            return {"approved": False, "score": 0, "reason": str(e)}

    async def check_repo_active(self, owner: str, repo: str) -> bool:
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
            if r.status_code == 200:
                return not r.json().get("archived", False)
            return False

    async def submit_github(self, bounty: Bounty, work: str) -> bool:
        try:
            parts = bounty.url.rstrip("/").split("/")
            if len(parts) < 7:
                return False
            owner, repo, issue_number = parts[-4], parts[-3], parts[-1]
            if not await self.check_repo_active(owner, repo):
                logger.warning(f"[submit] Repo archived: {owner}/{repo}")
                return False
            api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
            comment = f"## 🤖 Bounty Submission\n\n{work}\n\n---\n**Payment:**\n- EVM: `{self.evm_wallet}`\n- Solana: `{self.sol_wallet}`"
            headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github+json"}
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(api_url, json={"body": comment}, headers=headers)
                if resp.status_code == 201:
                    logger.info(f"[submit] ✅ Posted: {resp.json().get('html_url')}")
                    return True
                else:
                    logger.error(f"[submit] GitHub {resp.status_code}: {resp.text[:100]}")
                    return False
        except Exception as e:
            logger.error(f"[submit] Error: {e}")
            return False

    async def process(self, bounty: Bounty, work: str) -> bool:
        logger.info(f"[submitter] Processing: {bounty.title[:50]}")
        from .ai_agent import GPT4oAgent
        agent = GPT4oAgent()

        # Audit με retry loop (max 5 φορές)
        MAX_RETRIES = 5
        best_work = work
        best_score = 0
        approved = False

        for attempt in range(1, MAX_RETRIES + 1):
            audit = await self.audit_work(bounty, work)
            score = audit.get("score", 0)
            logger.info(f"[submitter] Attempt {attempt}/{MAX_RETRIES} — Score: {score}/100")

            if score > best_score:
                best_score = score
                best_work = work

            if score >= 80:  # require high quality
                approved = True
                logger.info(f"[submitter] ✅ Approved on attempt {attempt}!")
                break

            if attempt < MAX_RETRIES:
                improvement = audit.get("improvements", audit.get("reason", ""))
                logger.warning(f"[submitter] ⚠️ Retrying ({attempt}/{MAX_RETRIES}): {improvement[:80]}")
                better_desc = (bounty.description or "") + "\nIMPROVEMENT NEEDED: " + improvement
                work = await agent.generate_work(
                    bounty.title,
                    better_desc,
                    "Provide complete, production-ready implementation with full error handling and tests."
                )

        if not approved:  # threshold: 60
            logger.warning(f"[submitter] ❌ Failed after {MAX_RETRIES} attempts. Best score: {best_score}/100")
            self._save_rejected(bounty, best_work, audit)
            return False

        work = best_work

        # Submit
        submitted = False
        if bounty.source == "github" and bounty.url and "github.com" in bounty.url:
            submitted = await self.submit_github(bounty, work)
        elif bounty.source == "superteam" and bounty.external_id:
            from .scrapers.superteam_submitter import SuperteamSubmitter
            st = SuperteamSubmitter()
            submitted = await st.submit(bounty.external_id, bounty.title, work, bounty.reward_usd or 0)
            if not submitted:
                self._save_for_manual(bounty, work, audit)
        else:
            self._save_for_manual(bounty, work, audit)
            submitted = True

        if submitted:
            await self.queue.update_status(bounty.uid, BountyStatus.SUBMITTED)
            logger.info(f"[submitter] ✅ Done: {bounty.title[:50]} | ${bounty.reward_usd}")
        return submitted

    def _save_rejected(self, bounty, work, audit):
        os.makedirs("/root/bounty_submissions/rejected", exist_ok=True)
        f = f"/root/bounty_submissions/rejected/{bounty.uid[:8]}.json"
        json.dump({"title": bounty.title, "url": bounty.url, "audit": audit, "work": work}, open(f, "w"), indent=2)

    def _save_for_manual(self, bounty, work, audit):
        os.makedirs("/root/bounty_submissions/manual", exist_ok=True)
        f = f"/root/bounty_submissions/manual/{bounty.uid[:8]}.json"
        json.dump({"title": bounty.title, "url": bounty.url, "reward": bounty.reward_usd, "audit": audit, "work": work}, open(f, "w"), indent=2)
        import subprocess
        subprocess.Popen(["git", "-C", "/root/bounty_hunter", "add", "-A"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["git", "-C", "/root/bounty_hunter", "commit", "-m", f"submission: {bounty.title[:50]}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["git", "-C", "/root/bounty_hunter", "push", "origin", "main"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"[submitter] 💾 Saved: {f}")

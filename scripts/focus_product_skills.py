"""Apply the reviewed product-promotion profile without removing skill files."""
import argparse,json,os,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['HERMES_HOME']=str(ROOT/'.hermes')
sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
from hermes_cli.config import load_config
from hermes_cli.skills_config import get_disabled_skills,save_disabled_skills
from tools.skills_tool import _find_all_skills
from agent.skill_utils import ESSENTIAL_SKILLS
KEEP={'product-prompt-optimize','product-video-plan','spoken-script','humanizer','product-summary','product-image-edit','canvas-editor','mono-color','overlay-plan','pdf','docx','powerpoint'}
# Only installed packages in this reviewed catalog are affected; future custom
# skills are not silently disabled by a recurring wildcard rule.
UNRELATED={'claude-code','codex','computer-use','hermes-agent','opencode','architecture-diagram','ascii-video','baoyu-infographic','claude-design','design-md','manim-video','p5js','popular-web-designs','songwriting-and-ai-music','email-inbox-triage','himalaya','learning-save-note','gif-search','songsee','youtube-content','obsidian','airtable','box','document-to-action-items','google-workspace','maps','meeting-action-items','notion','product-price-monitor','teams-meeting-pipeline','weekly-review-planning','xlsx','arxiv','competitor-news-monitor','grounded-citations','llm-wiki','codebase-inspection','dogfood','github','hermes-agent-skill-authoring','inspecting-hermes-desktop-dom','node-inspect-debugger','requesting-code-review','simplify-code','spike','systematic-debugging','test-driven-development','blocked-page-recovery'}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 cfg=load_config();disabled=get_disabled_skills(cfg);installed={s['name'] for s in _find_all_skills(skip_disabled=True)};changes=sorted((installed&UNRELATED)-disabled-ESSENTIAL_SKILLS)
 record={'at':datetime.now().isoformat(),'previous_disabled':sorted(disabled),'disabled_now':changes,'retained':sorted(installed&KEEP),'tool_groups':cfg.get('platform_toolsets',{}).get('cli',[])}
 if args.apply:
  path=ROOT/'.hermes/skill-backups'/('product-profile-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
  save_disabled_skills(cfg,disabled|set(changes));print(f'已停用 {len(changes)} 个无关技能；保留 {len(record["retained"])} 个宣传与交付技能。备份：{path}')
 else:print(json.dumps(record,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

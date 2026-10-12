import {useState} from 'react';
import type {DirectorQuestion} from './director-conversation';

export function DirectorQuestions({questions,disabled,onAnswer}:{questions:DirectorQuestion[];disabled:boolean;onAnswer:(answer:string)=>Promise<boolean>}) {
  const [answers,setAnswers]=useState<string[]>(questions.map(()=>''));
  const [sending,setSending]=useState(false),[sent,setSent]=useState(false),[error,setError]=useState('');
  const blocked=disabled||sending||sent;
  function update(index:number,value:string){setAnswers(current=>current.map((answer,i)=>i===index?value:answer));setError('');}
  return <form className="director-questions" aria-label="回答助手的问题" onSubmit={e=>{e.preventDefault();if(blocked||answers.some(a=>!a.trim()))return;setSending(true);setError('');void onAnswer(questions.map((q,i)=>`${q.title}\n${answers[i].trim()}`).join('\n\n')).then(ok=>{if(ok)setSent(true);else setError('尚未发送，回答已保留。');}).catch(()=>setError('发送未完成，回答已保留。')).finally(()=>setSending(false));}}>
    {questions.map((q,index)=><fieldset key={index} disabled={blocked}><legend>{q.title}</legend><div className="director-question-options">{q.options.map(option=><button key={option} type="button" aria-pressed={answers[index]===option} onClick={()=>update(index,option)}>{option}</button>)}</div><input aria-label={`${q.title} 自由回答`} placeholder="或直接写你的想法" value={answers[index]} maxLength={1000} onChange={e=>update(index,e.target.value)}/></fieldset>)}
    <div><span role="status">{sent?'已回答':error}</span><button type="submit" disabled={blocked||answers.some(a=>!a.trim())}>{sending?'发送中…':sent?'已回答':'告诉助手'}</button></div>
  </form>;
}

interface Props { page: string; latestRun: string; }
export function StudioHeader({page,latestRun}:Props) {
  const links = [["Workspace","#home","home"],["Results","#results/"+encodeURIComponent(latestRun||"demo")+"/overview","results"],["Methods","#methods","methods"]];
  return <div className="nav"><a className="brand" href="#home">piRNA Studio</a><nav aria-label="Primary">{links.map(([label,href,key])=><a key={key} href={href} className={page===key?"active":""} aria-current={page===key?"page":undefined}>{label}</a>)}</nav></div>;
}

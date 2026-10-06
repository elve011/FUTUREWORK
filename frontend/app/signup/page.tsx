"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Command, LoaderCircle, ShieldCheck } from "lucide-react";
import { postAuth } from "../../lib/auth";

export default function SignupPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [githubLogin, setGithubLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await postAuth("signup", { display_name: displayName, email, password, github_login: githubLogin });
      router.replace("/");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Création du compte impossible."); }
    finally { setBusy(false); }
  }

  return <main className="auth-page">
    <Link className="auth-brand" href="/"><span className="brand-mark"><Command size={19} /></span> FUTURE<span>WORK</span></Link>
    <section className="auth-card" aria-labelledby="signup-title">
      <span className="auth-icon"><ShieldCheck size={20} /></span>
      <div className="panel-overline">FREELANCER WORKSPACE</div>
      <h1 id="signup-title">Créer un compte</h1>
      <p>Ton espace personnel isolera tes projets et ton historique.</p>
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="display-name">Nom complet</label>
        <input id="display-name" name="display_name" autoComplete="name" required minLength={2} maxLength={120} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        <label htmlFor="email">Adresse e-mail</label>
        <input id="email" name="email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} />
        <label htmlFor="github-login">Identifiant GitHub <span>(facultatif)</span></label>
        <input id="github-login" name="github_login" autoComplete="off" maxLength={39} placeholder="ex. emna-abdelli" value={githubLogin} onChange={(event) => setGithubLogin(event.target.value)} />
        <label htmlFor="password">Mot de passe <span>(12 caractères minimum)</span></label>
        <input id="password" name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} />
        {error && <div className="auth-error" role="alert">{error}</div>}
        <button className="primary-button auth-submit" type="submit" disabled={busy}>{busy ? <><LoaderCircle size={15} className="auth-spinner" /> Création…</> : "Créer mon compte"}</button>
      </form>
      <div className="auth-switch">Déjà inscrite ? <Link href="/login">Se connecter</Link></div>
      <div className="auth-security"><ShieldCheck size={14} /> Le champ GitHub est un identifiant public, jamais un token.</div>
    </section>
  </main>;
}

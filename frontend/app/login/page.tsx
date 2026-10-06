"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Command, LoaderCircle, ShieldCheck } from "lucide-react";
import { postAuth } from "../../lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await postAuth("login", { email, password });
      router.replace("/");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Connexion impossible."); }
    finally { setBusy(false); }
  }

  return <main className="auth-page">
    <Link className="auth-brand" href="/"><span className="brand-mark"><Command size={19} /></span> FUTURE<span>WORK</span></Link>
    <section className="auth-card" aria-labelledby="login-title">
      <span className="auth-icon"><ShieldCheck size={20} /></span>
      <div className="panel-overline">FREELANCER WORKSPACE</div>
      <h1 id="login-title">Connexion</h1>
      <p>Connecte-toi pour retrouver tes projets, preuves et suivis.</p>
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="email">Adresse e-mail</label>
        <input id="email" name="email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} />
        <label htmlFor="password">Mot de passe</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        {error && <div className="auth-error" role="alert">{error}</div>}
        <button className="primary-button auth-submit" type="submit" disabled={busy}>{busy ? <><LoaderCircle size={15} className="auth-spinner" /> Connexion…</> : "Se connecter"}</button>
      </form>
      <div className="auth-switch">Pas encore de compte ? <Link href="/signup">Créer un compte freelancer</Link></div>
      <div className="auth-security"><ShieldCheck size={14} /> Session sécurisée · aucun secret blockchain dans le navigateur</div>
    </section>
  </main>;
}

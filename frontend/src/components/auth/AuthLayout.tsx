import React from "react";
import { BookOpen } from "lucide-react";
import "../../styles/auth-styles.css";

interface AuthLayoutProps {
  title: string;
  /** One plain sentence under the title. */
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

/** Sign in, create account and reset password: one centred card (WP-D14). */
const AuthLayout: React.FC<AuthLayoutProps> = ({ title, description, children, footer }) => (
  <main id="main" className="auth-shell">
    <div className="auth-card">
      <p className="auth-card__brand">
        <span className="auth-card__mark" aria-hidden="true"><BookOpen /></span>
        Nexus
      </p>
      <header className="auth-card__header">
        <h1 tabIndex={-1}>{title}</h1>
        {description && <p className="auth-card__description">{description}</p>}
      </header>
      <div className="auth-card__body">{children}</div>
      {footer && <footer className="auth-card__footer">{footer}</footer>}
    </div>
  </main>
);

export default AuthLayout;

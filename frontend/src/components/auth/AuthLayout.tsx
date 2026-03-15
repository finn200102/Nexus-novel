import React from "react";
import "../../styles/auth-styles.css";

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

const AuthLayout: React.FC<AuthLayoutProps> = ({
  title,
  subtitle,
  children,
  footer,
}) => {
  return (
    <section className="auth-shell">
      <div className="auth-panel">
        <header className="auth-panel__header">
          <p>{subtitle}</p>
          <h1>{title}</h1>
        </header>
        <div className="auth-panel__body">{children}</div>
        {footer && <footer className="auth-panel__footer">{footer}</footer>}
      </div>
      <div className="auth-visual">
        <div className="auth-visual__overlay">
          <h2>Curate your universe</h2>
          <p>Sync every saga, bookmark new chapters, and dive back in instantly.</p>
        </div>
      </div>
    </section>
  );
};

export default AuthLayout;

import React from "react";
import { Link } from "react-router-dom";
import LoginForm from "../components/auth/LoginForm";
import AuthLayout from "../components/auth/AuthLayout";

const LoginPage: React.FC = () => {
  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to Nexus Novel"
      footer={
        <p>
          New here? <Link to="/signup">Create an account</Link>
        </p>
      }
    >
      <LoginForm />
    </AuthLayout>
  );
};

export default LoginPage;

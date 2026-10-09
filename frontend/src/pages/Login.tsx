import React from "react";
import { Link } from "react-router-dom";
import LoginForm from "../components/auth/LoginForm";
import AuthLayout from "../components/auth/AuthLayout";
import SingleSignOn from "../components/auth/SingleSignOn";

const LoginPage: React.FC = () => {
  return (
    <AuthLayout
      title="Sign in"
      description="Welcome back. Your library is waiting."
      footer={
        <p>
          New here? <Link to="/signup">Create an account</Link>
        </p>
      }
    >
      <SingleSignOn><LoginForm /></SingleSignOn>
    </AuthLayout>
  );
};

export default LoginPage;

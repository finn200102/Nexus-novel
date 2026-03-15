import React from "react";
import { Link } from "react-router-dom";
import SignupForm from "../components/auth/SignupForm";
import AuthLayout from "../components/auth/AuthLayout";

const SignupPage: React.FC = () => {
  return (
    <AuthLayout
      title="Create your account"
      subtitle="Join Nexus Novel"
      footer={
        <p>
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      }
    >
      <SignupForm />
    </AuthLayout>
  );
};

export default SignupPage;

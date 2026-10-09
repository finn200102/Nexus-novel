import React from "react";
import { Link } from "react-router-dom";
import SignupForm from "../components/auth/SignupForm";
import AuthLayout from "../components/auth/AuthLayout";

const SignupPage: React.FC = () => {
  return (
    <AuthLayout
      title="Create account"
      description="Save stories from your favourite sites and read them in one place."
      footer={
        <p>
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      }
    >
      <SignupForm />
    </AuthLayout>
  );
};

export default SignupPage;

// src/App.tsx
import React, { useState } from "react";

function App() {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div className="flex items-center justify-center min-h-screen p-4 bg-gradient-to-br from-gray-900 via-purple-900 to-violet-800 sm:p-6 md:p-8">
      {/* Glass card container */}
      <div className="grid w-full max-w-4xl overflow-hidden transition-all duration-500 border shadow-2xl backdrop-blur-md bg-white/10 rounded-xl border-white/20 md:grid-cols-2">
        {/* Left side - Hero image */}
        <div className="relative h-64 overflow-hidden md:h-auto">
          <div className="absolute inset-0 bg-gradient-to-br from-violet-500/80 to-fuchsia-500/80 mix-blend-overlay"></div>
          <img
            src="https://images.unsplash.com/photo-1532012197267-da84d127e765?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=987&q=80"
            alt="Books on shelf"
            className="object-cover object-center w-full h-full"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent"></div>
          <div className="absolute bottom-0 left-0 p-6">
            <span className="px-2 py-1 text-xs font-medium tracking-wider text-white rounded-full bg-white/20 backdrop-blur-sm">
              PREMIUM EXPERIENCE
            </span>
          </div>
        </div>

        {/* Right side - Content */}
        <div className="flex flex-col justify-between p-6 md:p-8">
          <div>
            <h1 className="mb-2 text-3xl font-bold tracking-tight text-white md:text-4xl">
              Nexus Novel
            </h1>
            <div className="w-20 h-1 mb-6 rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500"></div>
            <p className="mb-6 text-gray-300">
              Your premium novel reading platform with immersive experiences,
              personalized recommendations, and a vast library of exclusive
              content.
            </p>

            <div className="mb-8 space-y-3">
              {[
                "Immersive reading experience",
                "Personalized recommendations",
                "Exclusive premium content",
                "Offline reading capabilities",
              ].map((feature, index) => (
                <div key={index} className="flex items-center">
                  <div className="flex items-center justify-center flex-shrink-0 w-5 h-5 rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500">
                    <svg
                      className="w-3 h-3 text-white"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="3"
                        d="M5 13l4 4L19 7"
                      ></path>
                    </svg>
                  </div>
                  <span className="ml-3 text-sm text-gray-300">{feature}</span>
                </div>
              ))}
            </div>
          </div>

          {/* CTA Button */}
          <div
            className="relative group"
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
          >
            <div
              className={`absolute -inset-0.5 bg-gradient-to-r from-violet-600 to-fuchsia-600 rounded-lg blur-md transition-all duration-500 group-hover:opacity-100 ${
                isHovered ? "opacity-100" : "opacity-75"
              }`}
            ></div>
            <button className="relative w-full py-3 px-6 bg-gray-900 rounded-lg text-white font-medium transition-all duration-200 transform group-hover:translate-y-[-2px]">
              Start Your Journey
              <span className="absolute transition-transform duration-200 transform -translate-y-1/2 right-4 top-1/2 group-hover:translate-x-1">
                →
              </span>
            </button>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 mt-8">
            {[
              { value: "10K+", label: "Novels" },
              { value: "2M+", label: "Readers" },
              { value: "99%", label: "Satisfaction" },
            ].map((stat, index) => (
              <div key={index} className="text-center">
                <div className="text-xl font-bold text-white">{stat.value}</div>
                <div className="text-xs text-gray-400">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Floating elements for visual interest */}
      <div className="fixed w-64 h-64 rounded-full top-20 left-10 bg-purple-600/30 filter blur-3xl opacity-20 animate-blob"></div>
      <div className="fixed rounded-full bottom-20 right-10 w-80 h-80 bg-violet-600/30 filter blur-3xl opacity-20 animate-blob animation-delay-2000"></div>
      <div className="fixed rounded-full top-1/2 left-1/3 w-72 h-72 bg-fuchsia-600/30 filter blur-3xl opacity-20 animate-blob animation-delay-4000"></div>

      {/* Add animation styles */}
      <style jsx>{`
        @keyframes blob {
          0% {
            transform: translate(0px, 0px) scale(1);
          }
          33% {
            transform: translate(30px, -50px) scale(1.1);
          }
          66% {
            transform: translate(-20px, 20px) scale(0.9);
          }
          100% {
            transform: translate(0px, 0px) scale(1);
          }
        }
        .animate-blob {
          animation: blob 7s infinite;
        }
        .animation-delay-2000 {
          animation-delay: 2s;
        }
        .animation-delay-4000 {
          animation-delay: 4s;
        }
      `}</style>
    </div>
  );
}

export default App;

# FRRouting model for llm-on-a-stick's stick-frr image. Oxidized 0.37 ships none (upstream PRs
# ytti/oxidized#2036 and #2572 were never merged). The `admin` user's login shell is vtysh, so an
# SSH exec request runs `vtysh -c <command>` and returns plain output.
class FRR < Oxidized::Model
  using Refinements

  prompt /^[\w.-]+# $/
  comment '! '

  cmd :secret do |cfg|
    cfg.gsub!(/^(\s*(?:password|enable password|neighbor \S+ password)) \S+/, '\1 <hidden>')
    cfg
  end

  cmd 'show running-config' do |cfg|
    cfg.sub(/\ABuilding configuration\.\.\.\n\nCurrent configuration:\n/, '')
  end

  cfg :ssh do
    exec true
  end
end
